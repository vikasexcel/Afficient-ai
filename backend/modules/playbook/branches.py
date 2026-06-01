"""Declarative playbook branching — evaluate rules after each qualification update.

Branches are stored as JSON on the playbook (and in version snapshots). After
each user turn the :func:`evaluate_branches` helper checks conditions against
the current :class:`~modules.ai.qualification.QualificationState` and returns
actions (persona switch, injected prompt block, objective override).

Rules are evaluated in ascending ``priority`` order; multiple rules may fire
in one turn unless ``once`` is set and the branch id is already in
``branches_fired``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from modules.ai.qualification import QualificationState


# Single source of truth for the keys that the matcher actually
# understands. New conditions must add their key here AND implement the
# corresponding branch in :meth:`BranchCondition.matches` -- otherwise
# from_dict() will reject them so rules can't silently no-op or
# always-match.
_ALLOWED_WHEN_KEYS = frozenset(
    {
        "qualification_status",
        "min_score",
        "max_score",
        "fields_all_answered",
        "fields_any_answered",
        "field_set_this_turn",
    }
)


@dataclass(frozen=True)
class BranchCondition:
    """When-clause for a branch rule."""

    qualification_status: str | list[str] | None = None
    min_score: int | None = None
    max_score: int | None = None
    fields_all_answered: list[str] | None = None
    fields_any_answered: list[str] | None = None
    field_set_this_turn: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BranchCondition:
        if not data:
            return cls()

        # Reject silently-ignored keys. The previous behaviour was to
        # treat unknown keys as no-ops, which meant branches with typos
        # (or with features not yet implemented like "any_keyword")
        # matched every single turn.
        unknown = set(data.keys()) - _ALLOWED_WHEN_KEYS
        if unknown:
            raise ValueError(
                "unknown branch condition keys: "
                + ", ".join(sorted(unknown))
                + f" (allowed: {sorted(_ALLOWED_WHEN_KEYS)})"
            )

        return cls(
            qualification_status=data.get("qualification_status"),
            min_score=data.get("min_score"),
            max_score=data.get("max_score"),
            fields_all_answered=data.get("fields_all_answered"),
            fields_any_answered=data.get("fields_any_answered"),
            field_set_this_turn=data.get("field_set_this_turn"),
        )

    def matches(
        self,
        qual: QualificationState,
        *,
        newly_set_fields: list[str],
    ) -> bool:
        status = qual.status()
        score = qual.score()

        if self.qualification_status is not None:
            allowed = self.qualification_status
            if isinstance(allowed, str):
                allowed = [allowed]
            if status not in allowed:
                return False

        if self.min_score is not None and score < self.min_score:
            return False
        if self.max_score is not None and score > self.max_score:
            return False

        answered = set(qual.answered_fields())
        if self.fields_all_answered:
            if not all(f in answered for f in self.fields_all_answered):
                return False
        if self.fields_any_answered:
            if not any(f in answered for f in self.fields_any_answered):
                return False
        if self.field_set_this_turn:
            if not any(f in newly_set_fields for f in self.field_set_this_turn):
                return False

        return True


@dataclass(frozen=True)
class BranchAction:
    """Then-clause for a branch rule."""

    switch_persona: str | None = None
    dynamic_block: str | None = None
    objective: str | None = None
    merge_context: dict[str, Any] = field(default_factory=dict)
    end_call: bool = False
    end_call_message: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BranchAction:
        if not data:
            return cls()
        merge = data.get("merge_context") or {}
        return cls(
            switch_persona=data.get("switch_persona"),
            dynamic_block=data.get("dynamic_block"),
            objective=data.get("objective"),
            merge_context=dict(merge) if isinstance(merge, dict) else {},
            end_call=bool(data.get("end_call", False)),
            end_call_message=data.get("end_call_message"),
        )


@dataclass(frozen=True)
class BranchRule:
    id: str
    name: str
    priority: int = 100
    once: bool = True
    when: BranchCondition = field(default_factory=BranchCondition)
    then: BranchAction = field(default_factory=BranchAction)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BranchRule:
        return cls(
            id=str(data.get("id", data.get("name", "branch"))),
            name=str(data.get("name", data.get("id", "branch"))),
            priority=int(data.get("priority", 100)),
            once=bool(data.get("once", True)),
            when=BranchCondition.from_dict(data.get("when")),
            then=BranchAction.from_dict(data.get("then")),
        )


@dataclass
class BranchEvaluationResult:
    """Merged outcome of all branches that fired this turn."""

    fired_branch_ids: list[str] = field(default_factory=list)
    switch_persona: str | None = None
    dynamic_block: str | None = None
    objective: str | None = None
    merge_context: dict[str, Any] = field(default_factory=dict)
    end_call: bool = False
    end_call_message: str | None = None


def parse_branch_rules(raw: list[dict[str, Any]] | None) -> list[BranchRule]:
    if not raw:
        return []
    rules = [BranchRule.from_dict(item) for item in raw]
    return sorted(rules, key=lambda r: r.priority)


def evaluate_branches(
    rules: list[BranchRule],
    qual: QualificationState,
    *,
    newly_set_fields: list[str],
    branches_fired: list[str],
) -> BranchEvaluationResult:
    """Evaluate rules; return merged actions for this turn."""

    result = BranchEvaluationResult()
    fired_set = set(branches_fired)
    blocks: list[str] = []

    for rule in rules:
        if rule.once and rule.id in fired_set:
            continue
        if not rule.when.matches(qual, newly_set_fields=newly_set_fields):
            continue

        result.fired_branch_ids.append(rule.id)
        fired_set.add(rule.id)

        action = rule.then
        if action.switch_persona:
            result.switch_persona = action.switch_persona
        if action.dynamic_block:
            blocks.append(action.dynamic_block.strip())
        if action.objective:
            result.objective = action.objective
        if action.merge_context:
            result.merge_context.update(action.merge_context)
        if action.end_call:
            result.end_call = True
            if action.end_call_message:
                result.end_call_message = action.end_call_message

    if blocks:
        result.dynamic_block = "\n\n".join(blocks)

    return result
