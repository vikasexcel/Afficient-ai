"""HTTP coverage for /api/v1/ai using a fake OpenAI client.

The router calls ``svc.openai.complete`` / ``svc.openai.stream_collected``;
we override the FastAPI dependency to swap in a deterministic fake so we
get full coverage without spending OpenAI tokens.
"""

from __future__ import annotations

import uuid

import pytest

from main import app
from modules.ai.dependencies import get_ai_service
from modules.ai.memory import ConversationMemory
from modules.ai.service import AIService
from tests._support.fakes import FakeOpenAIClient


pytestmark = pytest.mark.api


@pytest.fixture
def fake_ai_service():
    """Swap the AI service dependency for a deterministic offline one."""

    fake = FakeOpenAIClient()
    memory = ConversationMemory()
    service = AIService(openai=fake, memory=memory)
    app.dependency_overrides[get_ai_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.pop(get_ai_service, None)


def test_personas_endpoint_lists_known_personas(client, auth_headers):
    r = client.get("/api/v1/ai/personas", headers=auth_headers)
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["personas"]}
    assert "outbound_sdr" in names


def test_generate_returns_fake_reply(client, auth_headers, fake_ai_service):
    r = client.post(
        "/api/v1/ai/generate",
        json={"prompt": "Hi", "system": "Be brief.", "max_tokens": 32},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["output"]
    assert body["model"] == "fake-gpt-4o"
    assert body["total_tokens"] == 59


def test_converse_writes_history_and_transcript(
    client, auth_headers, fake_ai_service
):
    call_id = f"pytest-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/v1/ai/converse",
        json={"call_id": call_id, "user_input": "I have $50k budget."},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["call_id"] == call_id
    assert body["reply"]
    assert body["history_length"] >= 2

    transcript = client.get(
        f"/api/v1/ai/calls/{call_id}/transcript", headers=auth_headers
    )
    assert transcript.status_code == 200
    body = transcript.json()
    assert len(body["entries"]) >= 2


def test_qualification_endpoint_returns_snapshot(
    client, auth_headers, fake_ai_service
):
    call_id = f"pytest-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/ai/converse",
        json={"call_id": call_id, "user_input": "Our budget is $50,000"},
        headers=auth_headers,
    )
    r = client.get(
        f"/api/v1/ai/calls/{call_id}/qualification", headers=auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["qualification"]["framework"] in {"BANT", "MEDDICC", "CUSTOM"}


def test_calls_listing_returns_call_we_just_made(
    client, auth_headers, fake_ai_service
):
    call_id = f"pytest-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/ai/converse",
        json={"call_id": call_id, "user_input": "hi"},
        headers=auth_headers,
    )
    r = client.get("/api/v1/ai/calls?limit=10", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert any(c["call_id"] == call_id for c in body["calls"])
