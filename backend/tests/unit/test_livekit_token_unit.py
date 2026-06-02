"""Unit tests for the LiveKit token minting helper.

We don't hit the LiveKit control plane here — :meth:`generate_token` is
pure JWT signing and so is fully testable offline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from modules.livekit.schema import TokenRequest
from modules.livekit.service import LiveKitService


pytestmark = pytest.mark.unit


def _svc() -> LiveKitService:
    return LiveKitService(
        url="wss://aifficient.test",
        api_key="APItest1234",
        api_secret="0123456789abcdefghijklmnopqrstuv",
    )


def test_generate_token_returns_valid_jwt():
    svc = _svc()
    req = TokenRequest(
        room="call-123", identity="user-1", ttl_minutes=10
    )
    tok = svc.generate_token(req)

    assert tok.token
    assert tok.room == "call-123"
    assert tok.identity == "user-1"
    assert tok.url == "wss://aifficient.test"
    # Token must decode with the same secret.
    payload = jwt.decode(tok.token, "0123456789abcdefghijklmnopqrstuv", algorithms=["HS256"])
    assert payload["iss"] == "APItest1234"
    assert payload["sub"] == "user-1"
    # Video grant for the requested room.
    grants = payload.get("video") or {}
    assert grants.get("room") == "call-123"
    assert grants.get("roomJoin") is True


def test_generate_token_expiry_matches_ttl():
    svc = _svc()
    tok = svc.generate_token(
        TokenRequest(room="r", identity="i", ttl_minutes=15)
    )
    delta = tok.expires_at - datetime.now(timezone.utc)
    # ±2 minutes is plenty of slack on slow CI hardware.
    assert timedelta(minutes=13) < delta <= timedelta(minutes=15, seconds=5)


def test_token_request_validates_required_fields():
    with pytest.raises(Exception):
        TokenRequest(room="", identity="")
