#!/usr/bin/env python3
"""Unit tests for the playbook module (no DB / Redis required for most)."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parents[1]
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.ai.prompts import render_system_prompt
from modules.ai.qualification import QualificationFramework, QualificationTracker
from modules.playbook.company import (
    DEFAULT_AGENT_NAME,
    company_prompt_block,
    resolve_agent_name,
    resolve_company_profile,
    resolve_opening_line,
)
from modules.playbook.runtime import PlaybookFieldRuntime, PlaybookRuntimeConfig
from modules.playbook.schema import CreatePlaybookInput, PlaybookFieldInput
from modules.playbook.seeds import default_playbook_specs


def test_default_specs() -> None:
    specs = default_playbook_specs()
    assert len(specs) == 3
    assert specs[0]["framework"] == "BANT"
    print("OK test_default_specs")


def test_render_with_playbook_fields() -> None:
    runtime = PlaybookRuntimeConfig(
        playbook_id=uuid.uuid4(),
        version=1,
        name="Test SDR",
        framework="BANT",
        persona_name="outbound_sdr",
        fields=[
            PlaybookFieldRuntime(
                key="budget",
                display_name="Budget",
                weight=2,
                required=True,
            ),
            PlaybookFieldRuntime(
                key="authority",
                display_name="Authority",
                weight=1,
            ),
        ],
    )
    prompt = render_system_prompt(
        persona="outbound_sdr",
        framework="BANT",
        extra_context={"lead_name": "Jane", "company": "Acme"},
        playbook=runtime,
    )
    assert "Budget" in prompt
    assert "Qualification playbook: Test SDR" in prompt
    print("OK test_render_with_playbook_fields")


def test_qualification_weighted_score() -> None:
    runtime = PlaybookRuntimeConfig(
        playbook_id=uuid.uuid4(),
        version=1,
        name="Weighted",
        framework="CUSTOM",
        persona_name="outbound_sdr",
        fields=[
            PlaybookFieldRuntime(key="budget", display_name="Budget", weight=3),
            PlaybookFieldRuntime(key="need", display_name="Need", weight=1),
        ],
    )
    state = QualificationTracker.empty_from_playbook(
        runtime, QualificationFramework.CUSTOM
    )
    state.fields["budget"] = "we have budget"
    assert state.score() == 75  # 3/4 weight answered
    print("OK test_qualification_weighted_score")


def test_company_prompt_and_opening() -> None:
    runtime = PlaybookRuntimeConfig(
        playbook_id=uuid.uuid4(),
        version=1,
        name="Co PB",
        framework="BANT",
        persona_name="outbound_sdr",
        company_name="Aifficient",
        company_intro="We help businesses generate more meetings using AI.",
        value_proposition="Increase qualified meetings by 3-4x.",
    )
    profile = resolve_company_profile(runtime)
    block = company_prompt_block(profile)
    assert "Company Name: Aifficient" in block
    assert "Value Proposition:" in block

    opening = resolve_opening_line(runtime, agent_name="Alex")
    assert opening is not None
    assert opening.startswith("Hi, this is Alex from Aifficient.")
    assert "We help businesses" in opening

    prompt = render_system_prompt(
        persona="outbound_sdr",
        framework="BANT",
        playbook=runtime,
    )
    assert "Company Name: Aifficient" in prompt
    print("OK test_company_prompt_and_opening")


def test_agent_name_resolution_and_opening() -> None:
    # With agent name + company.
    rt = PlaybookRuntimeConfig(
        playbook_id=uuid.uuid4(),
        version=1,
        name="Agent PB",
        framework="BANT",
        persona_name="outbound_sdr",
        agent_name="Terry",
        company_name="Aifficient",
    )
    assert resolve_agent_name(rt) == "Terry"
    opening = resolve_opening_line(rt, agent_name=resolve_agent_name(rt))
    assert opening == "Hi, this is Terry from Aifficient."

    # Agent name, no company.
    rt2 = PlaybookRuntimeConfig(
        playbook_id=uuid.uuid4(),
        version=1,
        name="Agent PB2",
        framework="BANT",
        persona_name="outbound_sdr",
        agent_name="Sarah",
    )
    assert (
        resolve_opening_line(rt2, agent_name=resolve_agent_name(rt2))
        == "Hi, this is Sarah."
    )

    # Backward compat: no agent name, no company -> fallback + no auto opening.
    rt3 = PlaybookRuntimeConfig(
        playbook_id=uuid.uuid4(),
        version=1,
        name="Legacy",
        framework="BANT",
        persona_name="outbound_sdr",
    )
    assert resolve_agent_name(rt3) == DEFAULT_AGENT_NAME
    assert resolve_opening_line(rt3, agent_name=resolve_agent_name(rt3)) is None

    # Prompt injects agent identity.
    prompt = render_system_prompt(
        persona="outbound_sdr", framework="BANT", playbook=rt
    )
    assert "Agent Name: Terry" in prompt
    print("OK test_agent_name_resolution_and_opening")


def test_field_input_validation() -> None:
    f = PlaybookFieldInput(key="budget", display_name="Budget")
    assert f.key == "budget"
    inp = CreatePlaybookInput(name="My PB", framework="BANT")
    assert inp.persona_name == "outbound_sdr"
    print("OK test_field_input_validation")


def main() -> int:
    tests = [
        test_default_specs,
        test_render_with_playbook_fields,
        test_qualification_weighted_score,
        test_field_input_validation,
        test_company_prompt_and_opening,
        test_agent_name_resolution_and_opening,
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
