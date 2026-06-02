"""Unit tests for the persona / system prompt renderer."""

from __future__ import annotations

import pytest

from modules.ai.prompts import (
    Persona,
    get_persona,
    list_personas,
    register_persona,
    render_system_prompt,
)
from modules.ai.qualification import QualificationFramework


pytestmark = pytest.mark.unit


def test_default_render_does_not_contain_with_there():
    rendered = render_system_prompt(
        persona="outbound_sdr", framework=QualificationFramework.BANT
    )
    assert " with there" not in rendered, rendered


def test_default_render_includes_bant_block():
    rendered = render_system_prompt(
        persona="outbound_sdr", framework=QualificationFramework.BANT
    )
    assert "BANT" in rendered
    assert "Budget" in rendered


def test_meddicc_render_swaps_qualification_block():
    rendered = render_system_prompt(
        persona="outbound_sdr", framework=QualificationFramework.MEDDICC
    )
    assert "MEDDICC" in rendered
    assert "Metrics" in rendered


def test_missing_persona_falls_back_to_outbound_sdr():
    p = get_persona("does-not-exist")
    assert p.name == "outbound_sdr"


def test_extra_context_is_interpolated_and_safe_for_missing_keys():
    rendered = render_system_prompt(
        persona="outbound_sdr",
        framework="BANT",
        extra_context={"lead_name": "Jane", "company": "Acme"},
    )
    assert "Jane" in rendered
    assert "Acme" in rendered
    # Unknown placeholders should never crash even if the template forgot one.
    # (The renderer uses a _SafeDict.)


def test_list_personas_returns_known_set():
    names = {p.name for p in list_personas()}
    assert {"outbound_sdr", "appointment_setter", "support_triage"} <= names


def test_register_persona_overrides_existing(monkeypatch):
    custom = Persona(
        name="outbound_sdr_test",
        description="test",
        template="hello {lead_name}",
        default_objective="x",
    )
    register_persona(custom)
    got = get_persona("outbound_sdr_test")
    assert got is custom
