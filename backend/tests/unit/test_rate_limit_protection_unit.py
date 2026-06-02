"""Unit tests for rate-limit middleware path helpers (no Redis)."""

from __future__ import annotations

import pytest

from common.security.protection import _is_exempt


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/health",
        "/api/v1/health",
        "/docs",
        "/openapi.json",
        "/api/v1/telephony/webhooks/voice",
        "/api/v1/telephony/webhooks/status",
    ],
)
def test_exempt_paths_match(path: str):
    assert _is_exempt(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/playbooks",
        "/api/v1/leads",
        "/api/v1/ai/converse",
        "/api/v1/telephony/webhookspoof",  # nearby but distinct prefix
    ],
)
def test_non_exempt_paths_dont_match(path: str):
    assert _is_exempt(path) is False
