"""Unit tests for the Answering Machine Detection (AMD) service.

Pure-Python — exercises the provider-agnostic answer-type mapping
(``detect_answer_type``) for Twilio's ``AnsweredBy`` vocabulary, the canonical
result space, confidence clamping, and the provider-registry plug-in seam.
"""

from __future__ import annotations

import pytest

from modules.telephony.amd import (
    AMD_HUMAN,
    AMD_UNKNOWN,
    AMD_VOICEMAIL,
    AMDResult,
    detect_answer_type,
    register_provider,
    supported_providers,
)


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Twilio provider mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "answered_by,expected",
    [
        ("human", AMD_HUMAN),
        ("machine_start", AMD_VOICEMAIL),
        ("machine_end_beep", AMD_VOICEMAIL),
        ("machine_end_silence", AMD_VOICEMAIL),
        ("machine_end_other", AMD_VOICEMAIL),
        ("fax", AMD_UNKNOWN),
        ("unknown", AMD_UNKNOWN),
    ],
)
def test_twilio_answered_by_maps_to_canonical(answered_by, expected):
    res = detect_answer_type(answered_by, provider="twilio")
    assert isinstance(res, AMDResult)
    assert res.result == expected
    assert res.raw == answered_by
    assert res.provider == "twilio"


def test_twilio_mapping_normalizes_case_and_hyphens():
    # Twilio may emit hyphenated / mixed-case variants on some flows.
    assert detect_answer_type("Machine-End-Beep").result == AMD_VOICEMAIL
    assert detect_answer_type("HUMAN").result == AMD_HUMAN
    assert detect_answer_type("  machine_start ").result == AMD_VOICEMAIL


def test_unrecognised_label_falls_back_to_unknown():
    assert detect_answer_type("gibberish").result == AMD_UNKNOWN
    assert detect_answer_type(None).result == AMD_UNKNOWN
    assert detect_answer_type("").result == AMD_UNKNOWN


# --------------------------------------------------------------------------- #
# Confidence
# --------------------------------------------------------------------------- #


def test_confidence_is_clamped_to_unit_interval():
    assert detect_answer_type("human", confidence=0.83).confidence == 0.83
    assert detect_answer_type("human", confidence=5.0).confidence == 1.0
    assert detect_answer_type("human", confidence=-1.0).confidence == 0.0
    assert detect_answer_type("human", confidence=None).confidence == 0.0
    assert detect_answer_type("human", confidence="bad").confidence == 0.0


def test_amd_result_helpers():
    assert detect_answer_type("human").is_human
    assert not detect_answer_type("human").is_voicemail
    assert detect_answer_type("machine_end_beep").is_voicemail


# --------------------------------------------------------------------------- #
# Provider registry (plug-in seam)
# --------------------------------------------------------------------------- #


def test_unknown_provider_passes_through_canonical_labels():
    # A provider that already speaks our vocabulary needs no mapper.
    assert detect_answer_type("voicemail", provider="acme").result == AMD_VOICEMAIL
    assert detect_answer_type("human", provider="acme").result == AMD_HUMAN
    # ...but non-canonical labels from an unknown provider are unknown.
    assert detect_answer_type("machine_start", provider="acme").result == AMD_UNKNOWN


def test_register_custom_provider():
    register_provider(
        "mock_amd",
        lambda raw: AMD_VOICEMAIL if raw.startswith("vm") else AMD_HUMAN,
    )
    assert "mock_amd" in supported_providers()
    assert detect_answer_type("vm_beep", provider="mock_amd").result == AMD_VOICEMAIL
    assert detect_answer_type("person", provider="mock_amd").result == AMD_HUMAN
