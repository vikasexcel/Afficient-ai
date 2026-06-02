"""Unit tests for declarative playbook branch evaluation."""

from __future__ import annotations

import pytest

from modules.ai.qualification import (
    FieldConfig,
    QualificationFramework,
    QualificationState,
)
from modules.playbook.branches import (
    BranchAction,
    BranchCondition,
    BranchRule,
    evaluate_branches,
    parse_branch_rules,
)


pytestmark = pytest.mark.unit


def _state_with(fields: dict[str, str | None]) -> QualificationState:
    state = QualificationState(
        framework=QualificationFramework.BANT,
        fields=dict(fields),
        field_configs={
            k: FieldConfig(key=k, weight=1, required=False) for k in fields
        },
    )
    return state


def test_condition_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown"):
        BranchCondition.from_dict({"any_keyword": ["price"]})


def test_min_score_blocks_low_score_branches():
    rule = BranchRule(
        id="warm",
        name="warm",
        when=BranchCondition(min_score=50),
        then=BranchAction(objective="book demo"),
    )
    state = _state_with({"budget": None, "authority": None})
    out = evaluate_branches([rule], state, newly_set_fields=[], branches_fired=[])
    assert out.fired_branch_ids == []


def test_min_score_fires_when_satisfied():
    rule = BranchRule(
        id="warm",
        name="warm",
        when=BranchCondition(min_score=50),
        then=BranchAction(objective="book demo"),
    )
    state = _state_with({"budget": "yes", "authority": "yes"})
    out = evaluate_branches([rule], state, newly_set_fields=[], branches_fired=[])
    assert out.fired_branch_ids == ["warm"]
    assert out.objective == "book demo"


def test_once_branches_dont_re_fire():
    rule = BranchRule(
        id="warm",
        name="warm",
        once=True,
        when=BranchCondition(min_score=50),
        then=BranchAction(objective="book demo"),
    )
    state = _state_with({"budget": "yes", "authority": "yes"})
    out = evaluate_branches(
        [rule], state, newly_set_fields=[], branches_fired=["warm"]
    )
    assert out.fired_branch_ids == []


def test_branches_sort_by_priority_and_merge_actions():
    rule_a = BranchRule(
        id="a",
        name="a",
        priority=10,
        when=BranchCondition(min_score=10),
        then=BranchAction(objective="objective-a"),
    )
    rule_b = BranchRule(
        id="b",
        name="b",
        priority=20,
        when=BranchCondition(min_score=10),
        then=BranchAction(objective="objective-b"),
    )
    state = _state_with({"budget": "yes"})
    parsed = parse_branch_rules(
        [
            {"id": "b", "name": "b", "priority": 20, "when": {"min_score": 10},
             "then": {"objective": "objective-b"}},
            {"id": "a", "name": "a", "priority": 10, "when": {"min_score": 10},
             "then": {"objective": "objective-a"}},
        ]
    )
    assert [r.id for r in parsed] == ["a", "b"]
    out = evaluate_branches(parsed, state, newly_set_fields=[], branches_fired=[])
    # Last objective wins (the higher-priority branch fires after).
    assert out.objective == "objective-b"
    assert out.fired_branch_ids == ["a", "b"]


def test_end_call_action_propagates():
    rule = BranchRule(
        id="dq",
        name="dq",
        when=BranchCondition(qualification_status="disqualified"),
        then=BranchAction(end_call=True, end_call_message="Goodbye"),
    )
    state = QualificationState(
        framework=QualificationFramework.BANT,
        fields={"budget": None},
        field_configs={"budget": FieldConfig(key="budget")},
        disqualified=True,
        disqualification_reason="opt-out",
    )
    out = evaluate_branches([rule], state, newly_set_fields=[], branches_fired=[])
    assert out.fired_branch_ids == ["dq"]
    assert out.end_call is True
    assert out.end_call_message == "Goodbye"


def test_field_set_this_turn_filter_blocks_until_match():
    rule = BranchRule(
        id="x",
        name="x",
        when=BranchCondition(field_set_this_turn=["budget"]),
        then=BranchAction(objective="advance"),
    )
    state = _state_with({"budget": "1000"})
    no_fire = evaluate_branches(
        [rule], state, newly_set_fields=["authority"], branches_fired=[]
    )
    fire = evaluate_branches(
        [rule], state, newly_set_fields=["budget"], branches_fired=[]
    )
    assert no_fire.fired_branch_ids == []
    assert fire.fired_branch_ids == ["x"]
