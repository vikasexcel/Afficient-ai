"""Objection handling for playbooks — rules, matching, prompt injection.

Objections are stored as JSON on the playbook (and in version snapshots),
mirroring :mod:`modules.playbook.branches`. Each rule carries:

* ``objection_type``     — predefined label (e.g. ``not_interested``) or ``custom``.
* ``objection_trigger``  — the canonical phrase a prospect might say.
* ``objection_response`` — what the AI should say back.
* ``fallback_response``  — a softer follow-up if the prospect pushes back.

Matching is intentionally dependency-free and deterministic so it can run on
every live turn and inside the playbook dry-run. We layer three strategies:

1. **Exact / substring** — the trigger phrase (or a synonym) appears in the
   normalised user text.
2. **Similar phrase**    — high :class:`difflib.SequenceMatcher` ratio against
   the trigger or a synonym.
3. **Semantic-ish**      — token (word-set) overlap against the trigger,
   synonyms, and the objection label.

Backward compatibility: a playbook with no objection rules behaves exactly as
before (no prompt block, no detection).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


# Predefined objection types. ``value`` is the stored key; ``label`` is for the
# UI; ``synonyms`` widen matching beyond the user-configured trigger phrase.
PREDEFINED_OBJECTIONS: dict[str, dict[str, Any]] = {
    "not_interested": {
        "label": "Not Interested",
        "synonyms": [
            "not interested",
            "not for me",
            "no thanks",
            "no thank you",
            "we're good",
            "we are good",
            "not right now",
        ],
    },
    "busy": {
        "label": "Busy",
        "synonyms": [
            "i'm busy",
            "im busy",
            "bad time",
            "in a meeting",
            "no time",
            "can't talk",
            "cant talk",
            "caught me at a bad time",
        ],
    },
    "send_information": {
        "label": "Send Information",
        "synonyms": [
            "send me information",
            "send me some information",
            "send info",
            "email me",
            "send me an email",
            "send me details",
            "send something over",
        ],
    },
    "already_using_another_solution": {
        "label": "Already Using Another Solution",
        "synonyms": [
            "already using",
            "we already have",
            "we already use",
            "we have something",
            "already have a solution",
            "using a competitor",
            "we use someone else",
        ],
    },
    "call_me_later": {
        "label": "Call Me Later",
        "synonyms": [
            "call me later",
            "call back later",
            "try me later",
            "another time",
            "reach out later",
            "follow up later",
        ],
    },
    "no_budget": {
        "label": "No Budget",
        "synonyms": [
            "no budget",
            "can't afford",
            "cant afford",
            "too expensive",
            "no money",
            "out of budget",
            "budget is tight",
        ],
    },
    "no_need": {
        "label": "No Need",
        "synonyms": [
            "no need",
            "don't need",
            "dont need",
            "we don't need this",
            "not needed",
            "no use for it",
        ],
    },
    "custom": {
        "label": "Custom",
        "synonyms": [],
    },
}

ALL_OBJECTION_TYPES = frozenset(PREDEFINED_OBJECTIONS.keys())

# Minimum similarity (0..1) for a fuzzy / semantic match to count.
_MATCH_THRESHOLD = 0.62


@dataclass(frozen=True)
class ObjectionRule:
    objection_type: str
    objection_trigger: str
    objection_response: str
    fallback_response: str | None = None

    @property
    def label(self) -> str:
        meta = PREDEFINED_OBJECTIONS.get(self.objection_type)
        return meta["label"] if meta else self.objection_type.replace("_", " ").title()

    def _candidate_phrases(self) -> list[str]:
        phrases = []
        if self.objection_trigger:
            phrases.append(self.objection_trigger)
        meta = PREDEFINED_OBJECTIONS.get(self.objection_type)
        if meta:
            phrases.extend(meta.get("synonyms", []))
        return [p for p in (_normalize(x) for x in phrases) if p]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObjectionRule:
        otype = str(data.get("objection_type", "custom")).strip().lower()
        if otype not in ALL_OBJECTION_TYPES:
            otype = "custom"
        return cls(
            objection_type=otype,
            objection_trigger=str(data.get("objection_trigger", "")).strip(),
            objection_response=str(data.get("objection_response", "")).strip(),
            fallback_response=(
                str(data.get("fallback_response")).strip()
                if data.get("fallback_response")
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "objection_type": self.objection_type,
            "objection_trigger": self.objection_trigger,
            "objection_response": self.objection_response,
            "fallback_response": self.fallback_response,
        }


@dataclass
class ObjectionMatch:
    rule: ObjectionRule
    score: float
    strategy: str  # "exact" | "similar" | "semantic"


def parse_objections(raw: list[dict[str, Any]] | None) -> list[ObjectionRule]:
    if not raw:
        return []
    rules: list[ObjectionRule] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rule = ObjectionRule.from_dict(item)
        # A rule with no usable response can't help the AI; skip it.
        if rule.objection_response:
            rules.append(rule)
    return rules


def _normalize(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if len(t) > 2}


def _token_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def match_objection(
    user_text: str,
    rules: list[ObjectionRule],
) -> ObjectionMatch | None:
    """Return the best objection match for a user turn, or ``None``.

    Tries exact/substring first (highest confidence), then fuzzy + token
    overlap. The rule with the highest combined score wins.
    """

    if not rules:
        return None

    norm_user = _normalize(user_text)
    if not norm_user:
        return None

    best: ObjectionMatch | None = None

    for rule in rules:
        phrases = rule._candidate_phrases()
        if not phrases:
            continue

        rule_best_score = 0.0
        rule_best_strategy = "semantic"

        for phrase in phrases:
            # 1. Exact / substring.
            if phrase and (phrase in norm_user or norm_user in phrase):
                rule_best_score = 1.0
                rule_best_strategy = "exact"
                break

            # 2. Fuzzy similarity.
            ratio = SequenceMatcher(None, norm_user, phrase).ratio()
            # 3. Semantic-ish token overlap.
            overlap = _token_overlap(norm_user, phrase)
            score = max(ratio, overlap)
            if score > rule_best_score:
                rule_best_score = score
                rule_best_strategy = "similar" if ratio >= overlap else "semantic"

        if rule_best_strategy != "exact" and rule_best_score < _MATCH_THRESHOLD:
            continue

        if best is None or rule_best_score > best.score:
            best = ObjectionMatch(
                rule=rule,
                score=round(rule_best_score, 3),
                strategy=rule_best_strategy,
            )
            if best.score >= 1.0:
                break

    return best


def objection_prompt_block(rules: list[ObjectionRule]) -> str:
    """Static system-prompt section listing all configured objection rules."""

    if not rules:
        return ""

    lines: list[str] = [
        "Objection handling — when the prospect raises one of these, respond "
        "naturally in your own words (do not read the script verbatim), then "
        "steer the conversation back to the call objective:",
    ]
    for i, rule in enumerate(rules, 1):
        trig = rule.objection_trigger or rule.label
        lines.append(
            f'{i}. {rule.label} (e.g. "{trig}")\n'
            f"   Response: {rule.objection_response}"
            + (
                f"\n   If they still resist: {rule.fallback_response}"
                if rule.fallback_response
                else ""
            )
        )
    lines.append(
        "Stay conversational and never sound scripted. After addressing the "
        "objection, return to advancing the call objective."
    )
    return "\n".join(lines)


def objection_turn_instruction(match: ObjectionMatch) -> str:
    """Per-turn dynamic block reinforcing the matched objection response."""

    rule = match.rule
    parts = [
        f"The prospect just raised the '{rule.label}' objection. "
        f"Address it using this guidance, rephrased naturally and "
        f"conversationally (do not quote it word-for-word): "
        f"{rule.objection_response}"
    ]
    if rule.fallback_response:
        parts.append(
            f"If they push back again, gently try: {rule.fallback_response}"
        )
    parts.append(
        "Then smoothly bring the conversation back to the call objective."
    )
    return " ".join(parts)


def objection_summary(rules: list[ObjectionRule]) -> dict[str, Any]:
    return {
        "objection_count": len(rules),
        "objection_types": [r.objection_type for r in rules],
    }
