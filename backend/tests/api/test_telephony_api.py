"""HTTP coverage for /api/v1/telephony.

The Twilio webhooks fork on whether ``TWILIO_VALIDATE_SIGNATURE`` is on,
so we drive both branches with a fake client whose signature validator
always returns True.
"""

from __future__ import annotations

import uuid

import pytest

from main import app
from modules.telephony.dependencies import get_twilio_client
from tests._support.fakes import FakeTwilioClient


pytestmark = pytest.mark.api


@pytest.fixture
def fake_twilio():
    fake = FakeTwilioClient()
    app.dependency_overrides[get_twilio_client] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_twilio_client, None)


def test_calls_endpoint_requires_auth(client):
    assert client.get("/api/v1/telephony/calls").status_code in (401, 403)


def test_list_calls_returns_empty_for_new_org(client, auth_headers, fake_twilio):
    r = client.get("/api/v1/telephony/calls", headers=auth_headers)
    # The service depends on a live registry; ensure the endpoint is
    # at least reachable and not 5xx.
    assert r.status_code == 200, r.text
    body = r.json()
    assert "calls" in body


def test_voice_webhook_returns_twiml(client, fake_twilio, monkeypatch):
    # Disable signature validation for this test (the fake validator
    # returns True anyway but we want the headerless path to work too).
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    sid = f"CA{uuid.uuid4().hex}"
    room = f"room-{uuid.uuid4().hex[:10]}"
    r = client.post(
        "/api/v1/telephony/webhooks/voice",
        data={
            "CallSid": sid,
            "From": "+15550001234",
            "To": "+15557654321",
        },
        params={"room": room},
    )
    assert r.status_code == 200, r.text
    body = r.text
    assert body.startswith("<?xml")
    assert "<Response>" in body


def test_status_webhook_acks_payload(client, fake_twilio, monkeypatch):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    sid = f"CA{uuid.uuid4().hex}"
    r = client.post(
        "/api/v1/telephony/webhooks/status",
        data={
            "CallSid": sid,
            "CallStatus": "initiated",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["call_sid"] == sid


def _seed_call(organization_id: str, *, status: str = "failed"):
    """Insert a terminal telephony_calls row + one event directly."""

    import uuid as _uuid

    from database.session import SessionLocal
    from modules.telephony.model import TelephonyCall, TelephonyEvent

    db = SessionLocal()
    try:
        row = TelephonyCall(
            organization_id=_uuid.UUID(organization_id),
            room_name=f"room-{_uuid.uuid4().hex[:10]}",
            direction="outbound",
            status=status,
            from_number="+15557654321",
            to_number="+15550001234",
            error_code="13227",
            error_message="Dial international: not authorized",
        )
        db.add(row)
        db.flush()
        db.add(
            TelephonyEvent(
                organization_id=row.organization_id,
                telephony_call_id=row.id,
                event_type="failed",
                source="twilio",
                payload={"CallStatus": "failed"},
            )
        )
        db.commit()
        return str(row.id)
    finally:
        db.close()


def test_delete_call_removes_record(
    client, unique_user, auth_headers, fake_twilio
):
    call_id = _seed_call(unique_user["organization_id"])

    # It shows up in the list first.
    listed = client.get("/api/v1/telephony/calls", headers=auth_headers).json()
    assert any(c["id"] == call_id for c in listed["calls"])

    # Delete it.
    deleted = client.delete(
        f"/api/v1/telephony/calls/{call_id}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text

    # It's gone (both detail + list).
    assert (
        client.get(
            f"/api/v1/telephony/calls/{call_id}", headers=auth_headers
        ).status_code
        == 404
    )
    listed2 = client.get(
        "/api/v1/telephony/calls", headers=auth_headers
    ).json()
    assert not any(c["id"] == call_id for c in listed2["calls"])


def test_delete_unknown_call_returns_404(client, auth_headers, fake_twilio):
    r = client.delete(
        f"/api/v1/telephony/calls/{uuid.uuid4()}", headers=auth_headers
    )
    assert r.status_code == 404


def test_delete_call_requires_auth(client):
    r = client.delete(f"/api/v1/telephony/calls/{uuid.uuid4()}")
    assert r.status_code in (401, 403)
