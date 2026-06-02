"""HTTP smoke tests for /api/v1/tts and /api/v1/stt (offline + fake)."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.api


def test_tts_voices_endpoint_requires_auth(client):
    assert client.get("/api/v1/tts/voices").status_code in (401, 403)


def test_stt_transcribe_endpoint_requires_auth(client):
    r = client.post(
        "/api/v1/stt/transcribe",
        json={"room": "x", "duration_seconds": 1},
    )
    assert r.status_code in (401, 403)


def test_tts_speak_endpoint_requires_auth(client):
    r = client.post(
        "/api/v1/tts/speak",
        json={"room": "x", "text": "hi"},
    )
    assert r.status_code in (401, 403)
