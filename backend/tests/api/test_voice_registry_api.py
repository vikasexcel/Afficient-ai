"""HTTP coverage for /api/v1/tts/voice-registry (US/UK simplified voices)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.api


def test_voice_registry_accents_us_uk_only(client, auth_headers):
    r = client.get("/api/v1/tts/voice-registry", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accents"] == ["US", "UK"]
    assert "Australian" not in body["accents"]


def test_voice_registry_filter_female_us(client, auth_headers):
    r = client.get(
        "/api/v1/tts/voice-registry",
        params={"gender": "female", "accent": "US"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    names = sorted(v["name"] for v in r.json()["voices"])
    assert names == ["Bella", "Rachel", "Sarah"]


def test_voice_registry_filter_male_uk(client, auth_headers):
    r = client.get(
        "/api/v1/tts/voice-registry",
        params={"gender": "male", "accent": "UK"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    names = sorted(v["name"] for v in r.json()["voices"])
    assert names == ["Arthur", "Callum", "George"]


def test_playbook_saves_uk_voice(client, auth_headers):
    import uuid

    reg = client.get(
        "/api/v1/tts/voice-registry",
        params={"gender": "female", "accent": "UK"},
        headers=auth_headers,
    ).json()
    charlotte = next(v for v in reg["voices"] if v["name"] == "Charlotte")

    payload = {
        "name": f"Voice PB {uuid.uuid4().hex[:6]}",
        "framework": "BANT",
        "persona_name": "outbound_sdr",
        "voice_provider": "elevenlabs",
        "voice_id": charlotte["voice_id"],
        "voice_name": charlotte["name"],
        "voice_gender": "female",
        "voice_accent": "UK",
        "fields": [
            {
                "key": "budget",
                "display_name": "Budget",
                "weight": 1,
                "required": False,
                "cue_patterns": [],
            }
        ],
    }
    create = client.post("/api/v1/playbooks", json=payload, headers=auth_headers)
    assert create.status_code == 201, create.text
    pb = create.json()
    assert pb["voice_name"] == "Charlotte"
    assert pb["voice_accent"] == "UK"
    assert pb["voice_id"] == charlotte["voice_id"]
