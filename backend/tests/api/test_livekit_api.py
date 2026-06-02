"""HTTP coverage for /api/v1/livekit using a fake service."""

from __future__ import annotations

import uuid

import pytest

from main import app
from modules.livekit.dependencies import get_livekit_service
from tests._support.fakes import FakeLiveKitService


pytestmark = pytest.mark.api


@pytest.fixture
def fake_livekit():
    fake = FakeLiveKitService()
    app.dependency_overrides[get_livekit_service] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_livekit_service, None)


def test_create_and_get_room_round_trip(client, auth_headers, fake_livekit):
    name = f"call-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/v1/livekit/rooms",
        json={"name": name, "empty_timeout": 60, "max_participants": 5},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == name
    assert body["empty_timeout"] == 60

    fetched = client.get(f"/api/v1/livekit/rooms/{name}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["name"] == name


def test_list_rooms_includes_created_room(client, auth_headers, fake_livekit):
    name = f"call-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/livekit/rooms",
        json={"name": name},
        headers=auth_headers,
    )
    r = client.get("/api/v1/livekit/rooms", headers=auth_headers)
    assert r.status_code == 200
    names = {room["name"] for room in r.json()["rooms"]}
    assert name in names


def test_delete_room_marks_session_deleted(client, auth_headers, fake_livekit):
    name = f"call-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/v1/livekit/rooms",
        json={"name": name},
        headers=auth_headers,
    )
    r = client.delete(f"/api/v1/livekit/rooms/{name}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] is True


def test_token_endpoint_returns_jwt(client, auth_headers, fake_livekit):
    r = client.post(
        "/api/v1/livekit/tokens",
        json={"room": "test-room", "identity": "user-1", "ttl_minutes": 5},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["room"] == "test-room"
    assert body["identity"] == "user-1"


def test_unauthenticated_caller_rejected(client, fake_livekit):
    r = client.get("/api/v1/livekit/rooms")
    assert r.status_code in (401, 403)
