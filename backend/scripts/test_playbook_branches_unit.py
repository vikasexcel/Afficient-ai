#!/usr/bin/env python3
"""Unit tests for playbook dynamic branching."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parents[1]
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.ai.qualification import QualificationFramework, QualificationTracker
from modules.playbook.branches import evaluate_branches, parse_branch_rules


def test_parse_and_fire_qualified_handoff() -> None:
    rules = parse_branch_rules(
        [
            {
                "id": "handoff",
                "name": "Handoff",
                "priority": 10,
                "once": True,
                "when": {"qualification_status": "qualified", "min_score": 75},
                "then": {
                    "switch_persona": "appointment_setter",
                    "dynamic_block": "Book a meeting.",
                },
            }
        ]
    )
    qual = QualificationTracker.empty(QualificationFramework.BANT)
    qual.fields["budget"] = "yes"
    qual.fields["authority"] = "vp"
    qual.fields["need"] = "pain"
    qual.fields["timeline"] = "q3"

    out = evaluate_branches(rules, qual, newly_set_fields=[], branches_fired=[])
    assert out.fired_branch_ids == ["handoff"]
    assert out.switch_persona == "appointment_setter"
    assert "Book a meeting" in (out.dynamic_block or "")
    print("OK test_parse_and_fire_qualified_handoff")


def test_once_only_fires_once() -> None:
    rules = parse_branch_rules(
        [
            {
                "id": "once_rule",
                "name": "Once",
                "priority": 1,
                "once": True,
                "when": {"min_score": 1},
                "then": {"dynamic_block": "A"},
            }
        ]
    )
    qual = QualificationTracker.empty(QualificationFramework.BANT)
    qual.fields["budget"] = "x"
    out1 = evaluate_branches(rules, qual, newly_set_fields=[], branches_fired=[])
    assert out1.fired_branch_ids == ["once_rule"]
    out2 = evaluate_branches(
        rules, qual, newly_set_fields=[], branches_fired=["once_rule"]
    )
    assert out2.fired_branch_ids == []
    print("OK test_once_only_fires_once")


def test_field_set_this_turn() -> None:
    rules = parse_branch_rules(
        [
            {
                "id": "budget_mentioned",
                "name": "Budget cue",
                "priority": 5,
                "once": False,
                "when": {"field_set_this_turn": ["budget"]},
                "then": {"dynamic_block": "Probe timeline next."},
            }
        ]
    )
    qual = QualificationTracker.empty(QualificationFramework.BANT)
    out = evaluate_branches(
        rules, qual, newly_set_fields=["budget"], branches_fired=[]
    )
    assert "budget_mentioned" in out.fired_branch_ids
    print("OK test_field_set_this_turn")


def main() -> int:
    tests = [
        test_parse_and_fire_qualified_handoff,
        test_once_only_fires_once,
        test_field_set_this_turn,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
