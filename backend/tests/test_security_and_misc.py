"""Rate limit, prompt + Twilio guard unit tests."""

from __future__ import annotations


async def test_rate_limit_async_blocks_after_max():
    """Async sliding-window limiter must raise 429 past max_requests."""

    import uuid

    from fastapi import HTTPException

    from common.security import rate_limit

    key = f"pytest:rl:{uuid.uuid4().hex[:8]}"

    try:
        for _ in range(3):
            await rate_limit.limit_async(key, max_requests=3, window=5)
        raised = False
        try:
            await rate_limit.limit_async(key, max_requests=3, window=5)
        except HTTPException as exc:
            assert exc.status_code == 429
            raised = True
        assert raised, "expected 429 not raised"
    finally:
        await rate_limit.reset_async(key)


def test_rate_limit_middleware_exempts_health_and_options(client):
    """Health probes + OPTIONS preflights must never be rate-limited.

    With RATE_LIMIT_ENABLED=false in conftest the middleware is fully
    off; we exercise the exemption logic directly instead.
    """
    from common.security.protection import _is_exempt

    assert _is_exempt("/api/v1/health")
    assert _is_exempt("/health")
    assert _is_exempt("/")
    assert _is_exempt("/api/v1/telephony/webhooks/voice")
    assert not _is_exempt("/api/v1/auth/login")
    assert not _is_exempt("/api/v1/playbooks")


def test_prompt_no_grammatical_default():
    """Bug 4.12 — default render must not say 'with there'."""

    from modules.ai.prompts import render_system_prompt

    rendered = render_system_prompt(persona="outbound_sdr", framework="BANT")
    assert " with there" not in rendered


def test_twilio_refuses_dummy_creds_in_production(monkeypatch):
    """Bug 4.14 — must refuse to mock in env=production."""

    import asyncio

    from config import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "ENV", "production")
    monkeypatch.setattr(settings_mod.settings, "TWILIO_ACCOUNT_SID", "ACdummy00000000")
    monkeypatch.setattr(settings_mod.settings, "TWILIO_AUTH_TOKEN", "")
    monkeypatch.setattr(settings_mod.settings, "TWILIO_API_KEY_SID", "SK1")
    monkeypatch.setattr(
        settings_mod.settings, "TWILIO_API_KEY_SECRET", "abc"
    )
    monkeypatch.setattr(
        settings_mod.settings, "TWILIO_PHONE_NUMBER", "+15551234567"
    )
    monkeypatch.setattr(
        settings_mod.settings,
        "TWILIO_PUBLIC_BASE_URL",
        "https://ex.test",
    )

    from modules.telephony.exceptions import TelephonyConfigError
    from modules.telephony.twilio_client import TwilioClient

    client = TwilioClient()

    async def _go():
        try:
            await client.create_call(to_number="+15551234567", room_name="r")
        except TelephonyConfigError as exc:
            assert "production" in str(exc).lower()
            return
        raise AssertionError("expected TelephonyConfigError in production")

    asyncio.run(_go())


def test_branch_condition_rejects_unknown_keys():
    """Bug 4.11 — direct unit assertion on the matcher."""

    import pytest

    from modules.playbook.branches import BranchCondition

    with pytest.raises(ValueError, match="unknown"):
        BranchCondition.from_dict({"any_keyword": ["price"]})
