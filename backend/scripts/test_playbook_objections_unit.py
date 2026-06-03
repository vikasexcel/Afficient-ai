#!/usr/bin/env python3
"""Unit tests for playbook objection matching (no DB)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parents[1]
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.ai.prompts import render_system_prompt
from modules.playbook.objections import (
    match_objection,
    objection_prompt_block,
    objection_turn_instruction,
    parse_objections,
)
from modules.playbook.runtime import PlaybookRuntimeConfig
import uuid


def test_send_information_exact() -> None:
    rules = parse_objections(
        [
            {
                "objection_type": "send_information",
                "objection_trigger": "send me information",
                "objection_response": (
                    "Absolutely, I can do that. But honestly, it might make "
                    "more sense to spend 10 minutes together first."
                ),
                "fallback_response": "Would tomorrow or Thursday be easier?",
            }
        ]
    )
    m = match_objection("Can you just send me some information?", rules)
    assert m is not None
    assert m.rule.objection_type == "send_information"
    assert m.strategy in ("exact", "similar", "semantic")
    assert "10 minutes" in objection_turn_instruction(m)
    print("OK test_send_information_exact")


def test_not_interested_synonym() -> None:
    rules = parse_objections(
        [
            {
                "objection_type": "not_interested",
                "objection_trigger": "Not interested",
                "objection_response": "Fair enough — quick question though.",
            }
        ]
    )
    m = match_objection("Yeah we're not for me right now", rules)
    assert m is not None
    assert m.rule.objection_type == "not_interested"
    print("OK test_not_interested_synonym")


def test_no_rules_no_match() -> None:
    assert match_objection("not interested", []) is None
    print("OK test_no_rules_no_match")


def test_prompt_block_injected() -> None:
    runtime = PlaybookRuntimeConfig(
        playbook_id=uuid.uuid4(),
        version=1,
        name="Obj PB",
        framework="BANT",
        persona_name="outbound_sdr",
        objections=[
            {
                "objection_type": "busy",
                "objection_trigger": "I'm busy",
                "objection_response": "I'll be brief.",
            }
        ],
    )
    prompt = render_system_prompt(
        persona="outbound_sdr", framework="BANT", playbook=runtime
    )
    assert "Objection handling" in prompt
    assert "Busy" in prompt
    block = objection_prompt_block(parse_objections(runtime.objections))
    assert "I'll be brief" in block
    print("OK test_prompt_block_injected")


def main() -> int:
    tests = [
        test_send_information_exact,
        test_not_interested_synonym,
        test_no_rules_no_match,
        test_prompt_block_injected,
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
