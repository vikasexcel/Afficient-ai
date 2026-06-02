"""Unit tests for TwiML construction (pure-string, no network)."""

from __future__ import annotations

import pytest

from modules.telephony.twilio_client import TwilioClient


pytestmark = pytest.mark.unit


def _client(**overrides) -> TwilioClient:
    base = {
        "account_sid": "ACdummy00000000000000000000000000",
        "auth_token": "test-auth-token",
        "phone_number": "+15551234567",
        "public_base_url": "https://api.test",
        "livekit_sip_uri": "fake.sip.livekit.cloud",
    }
    base.update(overrides)
    return TwilioClient(**base)


def test_twiml_emits_sip_dial_when_sip_uri_present():
    client = _client()
    xml = client.build_voice_twiml(room_name="call-123")
    assert "<Dial" in xml
    assert "<Sip>sip:call-123@fake.sip.livekit.cloud</Sip>" in xml
    assert "answerOnBridge=\"true\"" in xml


def test_twiml_falls_back_to_say_when_sip_missing(monkeypatch):
    # The TwilioClient constructor falls back to ``settings.LIVEKIT_SIP_URI``
    # when the passed value is falsy, so blank both out to exercise the
    # missing-SIP branch.
    from config import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "LIVEKIT_SIP_URI", "", raising=False)
    client = _client(livekit_sip_uri="")
    xml = client.build_voice_twiml(room_name="call-123")
    assert "<Dial" not in xml
    assert "<Say>" in xml
    assert "<Hangup/>" in xml


def test_twiml_includes_opening_say_when_provided():
    client = _client()
    xml = client.build_voice_twiml(
        room_name="call-x", opening_say="Hello there!"
    )
    assert "<Say>Hello there!</Say>" in xml


def test_twiml_escapes_special_characters():
    client = _client()
    xml = client.build_voice_twiml(
        room_name="call-x", opening_say="Tom & Jerry <hi>"
    )
    assert "&amp;" in xml
    assert "&lt;hi&gt;" in xml


def test_validate_signature_returns_false_without_signature_header():
    client = _client()
    assert (
        client.validate_signature(url="https://x.test/", params={}, signature=None)
        is False
    )
