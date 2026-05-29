"""BANT / MEDDICC qualification tracker.

The tracker is intentionally rule-based, not LLM-based:

* It scans each user turn for cue keywords/phrases that indicate one of
  the qualification fields was discussed.
* It maintains a per-call snapshot in Redis (alongside the chat memory).
* It exposes a :class:`QualificationSnapshot` for the API and for
  inclusion in the final call summary.

Why rule-based? Because we want monotonic, deterministic progress that
the orchestrator can act on (e.g. switch from `outbound_sdr` to
`appointment_setter` once BANT score crosses a threshold). Letting the
LLM self-report would be noisy and would burn tokens on every turn.

For higher fidelity, downstream pipelines can re-score transcripts with
an LLM at end-of-call — that lives in :mod:`modules.ai.service` (call
summary generation).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable

from modules.ai.schema import QualificationSnapshot


class QualificationFramework(str, Enum):
    BANT = "BANT"
    MEDDICC = "MEDDICC"


# ---------------------------------------------------------------------------
# Cue dictionaries
# ---------------------------------------------------------------------------
#
# Each entry maps a qualification field to a list of regex patterns. Patterns
# are intentionally permissive — we want recall high since the LLM-led
# summariser at end-of-call will refine. Order doesn't matter.

_BANT_CUES: dict[str, list[str]] = {
    "budget": [
        r"\bbudget\b",
        r"\bspend(ing)?\b",
        r"\bafford\b",
        r"\bprice|pricing|cost|costs?\b",
        r"\$\s*\d",
        r"\bdollars?\b|\beuros?\b|\bpounds?\b",
        r"\bquote\b|\bquotation\b",
    ],
    "authority": [
        r"\b(decision[- ]?maker|decide|approve|approver|sign[- ]?off)\b",
        r"\b(ceo|cto|cfo|coo|vp|director|head of|owner)\b",
        r"\bmy team\b|\bmy boss\b|\breport(s)? to\b",
        r"\bI (decide|approve|own)\b",
    ],
    "need": [
        r"\b(problem|pain|challenge|struggle|issue|frustrat|bottleneck)\b",
        r"\b(looking for|need(ed)?|require|trying to)\b",
        r"\b(replace|upgrade|switch from)\b",
    ],
    "timeline": [
        r"\b(this|next) (week|month|quarter|year)\b",
        r"\b(q[1-4]|h[12])\b",
        r"\b(by|before|after) \w+",
        r"\b(asap|immediately|urgent|today|tomorrow)\b",
        r"\b\d{1,2} (days?|weeks?|months?)\b",
    ],
}


_MEDDICC_CUES: dict[str, list[str]] = {
    "metrics": [
        r"\b\d+\s*(%|percent|x|hours?|days?|users?|calls?|leads?)\b",
        r"\b(roi|kpi|metric|measure|increase|reduce|save|cut)\b",
    ],
    "economic_buyer": [
        r"\b(ceo|cfo|coo|vp|head of finance|controller|budget owner)\b",
        r"\b(sign(s)? the cheque|signs the contract|approves the spend)\b",
    ],
    "decision_criteria": [
        r"\b(criteria|requirement|must[- ]?have|nice[- ]?to[- ]?have)\b",
        r"\b(evaluat|compar|shortlist|rfp|rfi)\b",
    ],
    "decision_process": [
        r"\b(process|steps?|stakeholders?|procurement|legal|security review)\b",
        r"\b(timeline|kickoff|go[- ]?live|onboarding)\b",
    ],
    "identify_pain": [
        r"\b(pain|problem|issue|risk|losing|costing|wasting|broken)\b",
    ],
    "champion": [
        r"\b(champion|advocate|internal sponsor|on my side|will push for)\b",
    ],
    "competition": [
        r"\b(competitor|alternative|currently using|in-?house|build vs buy)\b",
        r"\b(also (looking at|evaluating))\b",
    ],
}


_CUES: dict[QualificationFramework, dict[str, list[str]]] = {
    QualificationFramework.BANT: _BANT_CUES,
    QualificationFramework.MEDDICC: _MEDDICC_CUES,
}


# Status thresholds: ratio of (answered fields / total fields)
_QUALIFIED_RATIO = 0.75
_IN_PROGRESS_RATIO = 0.01


# ---------------------------------------------------------------------------
# State container
# ---------------------------------------------------------------------------


@dataclass
class QualificationState:
    """In-memory state for one call's qualification progress.

    ``fields`` stores the most recent user-turn snippet that triggered each
    field. We deliberately keep snippets short so the call summary stays
    cheap to render.
    """

    framework: QualificationFramework = QualificationFramework.BANT
    fields: dict[str, str | None] = field(default_factory=dict)
    last_updated: datetime | None = None
    disqualified: bool = False
    disqualification_reason: str | None = None

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def all_field_names(self) -> list[str]:
        return list(_CUES[self.framework].keys())

    def _ensure_keys(self) -> None:
        for k in self.all_field_names():
            self.fields.setdefault(k, None)

    def ingest_user_turn(self, text: str) -> list[str]:
        """Update state from a user message; return list of newly-set fields."""

        self._ensure_keys()
        if not text or not text.strip():
            return []

        lower = text.lower()
        # Disqualification cues short-circuit everything.
        if re.search(
            r"\b(remove me|do not call|do(?:n'?t)? call (me )?again|"
            r"not interested|stop calling|take me off|unsubscribe)\b",
            lower,
        ):
            self.disqualified = True
            self.disqualification_reason = "explicit opt-out"
            self.last_updated = datetime.now(timezone.utc)
            return ["__disqualified__"]

        newly_set: list[str] = []
        snippet = text.strip()[:240]
        for field_name, patterns in _CUES[self.framework].items():
            if self.fields.get(field_name):
                # We already have a snippet — keep the earliest for stability,
                # but extend it if the new snippet adds materially (rare).
                continue
            for pat in patterns:
                if re.search(pat, lower):
                    self.fields[field_name] = snippet
                    newly_set.append(field_name)
                    break

        if newly_set:
            self.last_updated = datetime.now(timezone.utc)
        return newly_set

    # ------------------------------------------------------------------
    # Derived values
    # ------------------------------------------------------------------

    def answered_fields(self) -> list[str]:
        self._ensure_keys()
        return [k for k, v in self.fields.items() if v]

    def pending_fields(self) -> list[str]:
        self._ensure_keys()
        return [k for k, v in self.fields.items() if not v]

    def score(self) -> int:
        names = self.all_field_names()
        if not names:
            return 0
        return int(round(100 * len(self.answered_fields()) / len(names)))

    def status(self) -> str:
        if self.disqualified:
            return "disqualified"
        ratio = (
            len(self.answered_fields()) / len(self.all_field_names())
            if self.all_field_names()
            else 0.0
        )
        if ratio >= _QUALIFIED_RATIO:
            return "qualified"
        if ratio >= _IN_PROGRESS_RATIO:
            return "in_progress"
        return "not_started"

    def snapshot(self) -> QualificationSnapshot:
        self._ensure_keys()
        return QualificationSnapshot(
            framework=self.framework.value,
            status=self.status(),  # type: ignore[arg-type]
            score=self.score(),
            answered_fields=self.answered_fields(),
            pending_fields=self.pending_fields(),
            fields=self.fields,
            last_updated=self.last_updated,
        )

    # ------------------------------------------------------------------
    # Persistence (JSON) — used by ConversationMemory
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(
            {
                "framework": self.framework.value,
                "fields": self.fields,
                "last_updated": (
                    self.last_updated.isoformat() if self.last_updated else None
                ),
                "disqualified": self.disqualified,
                "disqualification_reason": self.disqualification_reason,
            }
        )

    @classmethod
    def from_json(cls, blob: str) -> "QualificationState":
        data = json.loads(blob)
        fw = QualificationFramework(data.get("framework", "BANT"))
        last = data.get("last_updated")
        return cls(
            framework=fw,
            fields=data.get("fields", {}),
            last_updated=datetime.fromisoformat(last) if last else None,
            disqualified=bool(data.get("disqualified", False)),
            disqualification_reason=data.get("disqualification_reason"),
        )


# ---------------------------------------------------------------------------
# Tracker (stateless helper around QualificationState)
# ---------------------------------------------------------------------------


class QualificationTracker:
    """Functional helpers that operate on :class:`QualificationState`.

    The state itself is owned by :class:`modules.ai.memory.ConversationMemory`
    so it's persisted with the chat history.
    """

    @staticmethod
    def empty(framework: QualificationFramework | str | None = None) -> QualificationState:
        fw = (
            framework
            if isinstance(framework, QualificationFramework)
            else (
                QualificationFramework(framework)
                if framework
                else QualificationFramework.BANT
            )
        )
        return QualificationState(framework=fw, fields={k: None for k in _CUES[fw]})

    @staticmethod
    def supported() -> Iterable[QualificationFramework]:
        return list(_CUES.keys())
