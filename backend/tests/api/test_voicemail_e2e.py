"""End-to-end coverage for AMD / Voicemail Drop.

Covers the full Phase-2 voicemail feature surface:

* Voicemail config API (GET/POST /campaigns/{id}/voicemail) + validation.
* Call flow: the voice webhook plays a voicemail drop on a machine answer,
  bridges to the AI room on a human answer, and follows the configured
  fallback on an unknown answer.
* Voicemail metrics aggregation on the campaign metrics endpoint.
* Retry engine honouring ``retry_on_voicemail`` (enabled vs disabled).
"""

from __future__ import annotations

import uuid

import pytest

from database.session import SessionLocal
from modules.campaign.execution_model import Execution
from modules.campaign.model import (
    CAMPAIGN_STATUS_ACTIVE,
    CAMPAIGN_STATUS_COMPLETED,
    Campaign,
)
from modules.campaign.retry import process_outcome
from modules.campaign.scheduler import CampaignScheduler
from modules.campaign.workflow_model import Workflow
from modules.telephony.dependencies import get_twilio_client
from modules.telephony.model import TelephonyCall
from main import app
from tests._support.fakes import FakeTwilioClient


pytestmark = pytest.mark.api


_WIDE_HOURS = {
    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "start": "00:00",
    "end": "23:59",
    "skip_holidays": False,
}
_UNLIMITED = {"calls_per_hour": 0, "max_concurrent_calls": 0}


@pytest.fixture
def fake_twilio():
    fake = FakeTwilioClient()
    app.dependency_overrides[get_twilio_client] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_twilio_client, None)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _create_campaign(client, headers, *, voicemail_config=None) -> str:
    cfg = {
        "name": f"VM {uuid.uuid4().hex[:6]}",
        "schedule": {"start_immediately": True, "timezone": "UTC"},
        "business_hours": _WIDE_HOURS,
        "pacing": _UNLIMITED,
    }
    if voicemail_config is not None:
        cfg["voicemail_config"] = voicemail_config
    r = client.post("/api/v1/campaigns", json=cfg, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_call(
    organization_id: str,
    *,
    campaign_id: str | None = None,
    call_sid: str | None = None,
    status: str = "in-progress",
    extra: dict | None = None,
    amd_result: str | None = None,
    voicemail_dropped: bool = False,
    parent_call_id: str | None = None,
) -> str:
    db = SessionLocal()
    try:
        row = TelephonyCall(
            organization_id=uuid.UUID(organization_id),
            campaign_id=uuid.UUID(campaign_id) if campaign_id else None,
            room_name=f"room-{uuid.uuid4().hex[:10]}",
            call_sid=call_sid,
            direction="outbound",
            status=status,
            from_number="+15557654321",
            to_number="+15550001234",
            extra=extra,
            amd_result=amd_result,
            voicemail_dropped=voicemail_dropped,
            parent_call_id=(
                uuid.UUID(parent_call_id) if parent_call_id else None
            ),
        )
        db.add(row)
        db.commit()
        return str(row.id)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Voicemail config API + validation
# --------------------------------------------------------------------------- #


def test_get_voicemail_defaults_to_disabled(client, auth_headers):
    cid = _create_campaign(client, auth_headers)
    r = client.get(f"/api/v1/campaigns/{cid}/voicemail", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["voicemail_enabled"] is False
    assert body["voicemail_message_url"] is None
    assert body["retry_on_voicemail"] is False


def test_configure_voicemail_by_url(client, auth_headers):
    cid = _create_campaign(client, auth_headers)
    r = client.post(
        f"/api/v1/campaigns/{cid}/voicemail",
        data={
            "voicemail_enabled": "true",
            "retry_on_voicemail": "true",
            "amd_unknown_fallback": "voicemail",
            "voicemail_message_url": "https://cdn.test/vm.mp3",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["voicemail_enabled"] is True
    assert body["voicemail_message_url"] == "https://cdn.test/vm.mp3"
    assert body["retry_on_voicemail"] is True
    assert body["amd_unknown_fallback"] == "voicemail"

    # GET reflects the persisted config.
    g = client.get(f"/api/v1/campaigns/{cid}/voicemail", headers=auth_headers)
    assert g.json()["voicemail_message_url"] == "https://cdn.test/vm.mp3"


def test_configure_voicemail_by_file_upload(client, auth_headers):
    cid = _create_campaign(client, auth_headers)
    r = client.post(
        f"/api/v1/campaigns/{cid}/voicemail",
        data={"voicemail_enabled": "true", "retry_on_voicemail": "false"},
        files={"file": ("greeting.mp3", b"ID3fakeaudio" * 64, "audio/mpeg")},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["voicemail_enabled"] is True
    assert body["voicemail_message_url"]  # a stored URL was produced


def test_voicemail_rejects_bad_url(client, auth_headers):
    cid = _create_campaign(client, auth_headers)
    r = client.post(
        f"/api/v1/campaigns/{cid}/voicemail",
        data={
            "voicemail_enabled": "true",
            "voicemail_message_url": "ftp://cdn.test/vm.mp3",
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text


def test_voicemail_rejects_bad_audio_format(client, auth_headers):
    cid = _create_campaign(client, auth_headers)
    r = client.post(
        f"/api/v1/campaigns/{cid}/voicemail",
        data={"voicemail_enabled": "true"},
        files={"file": ("malware.exe", b"MZ" * 100, "application/octet-stream")},
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text


def test_voicemail_enabled_requires_recording(client, auth_headers):
    cid = _create_campaign(client, auth_headers)
    r = client.post(
        f"/api/v1/campaigns/{cid}/voicemail",
        data={"voicemail_enabled": "true"},
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text


def test_voicemail_config_requires_auth(client):
    r = client.get(f"/api/v1/campaigns/{uuid.uuid4()}/voicemail")
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------- #
# Call flow (voice webhook + AMD)
# --------------------------------------------------------------------------- #


def _post_voice(client, *, call_sid, answered_by=None):
    data = {
        "CallSid": call_sid,
        "From": "+15550001234",
        "To": "+15557654321",
    }
    if answered_by is not None:
        data["AnsweredBy"] = answered_by
    return client.post("/api/v1/telephony/webhooks/voice", data=data)


def test_call_flow_voicemail_drop_plays_recording(
    client, unique_user, auth_headers, fake_twilio, monkeypatch
):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    sid = f"CA{uuid.uuid4().hex}"
    url = "https://cdn.test/vm.mp3"
    _seed_call(
        unique_user["organization_id"],
        call_sid=sid,
        extra={
            "voicemail": {
                "enabled": True,
                "message_url": url,
                "unknown_fallback": "human",
            }
        },
    )
    r = _post_voice(client, call_sid=sid, answered_by="machine_end_beep")
    assert r.status_code == 200, r.text
    assert "<Play>" in r.text
    assert url in r.text
    assert "<Dial" not in r.text


def test_call_flow_human_bridges_to_agent(
    client, unique_user, auth_headers, fake_twilio, monkeypatch
):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    sid = f"CA{uuid.uuid4().hex}"
    _seed_call(
        unique_user["organization_id"],
        call_sid=sid,
        extra={
            "voicemail": {
                "enabled": True,
                "message_url": "https://cdn.test/vm.mp3",
                "unknown_fallback": "human",
            }
        },
    )
    r = _post_voice(client, call_sid=sid, answered_by="human")
    assert r.status_code == 200, r.text
    # Human -> normal SIP bridge, no voicemail playback.
    assert "<Play>" not in r.text
    assert "<Dial" in r.text


def test_call_flow_unknown_follows_fallback(
    client, unique_user, auth_headers, fake_twilio, monkeypatch
):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    # Default fallback = human -> bridge.
    sid = f"CA{uuid.uuid4().hex}"
    _seed_call(
        unique_user["organization_id"],
        call_sid=sid,
        extra={
            "voicemail": {
                "enabled": True,
                "message_url": "https://cdn.test/vm.mp3",
                "unknown_fallback": "human",
            }
        },
    )
    r = _post_voice(client, call_sid=sid, answered_by="unknown")
    assert "<Play>" not in r.text and "<Dial" in r.text

    # Fallback = voicemail -> drop even on unknown.
    sid2 = f"CA{uuid.uuid4().hex}"
    url = "https://cdn.test/vm2.mp3"
    _seed_call(
        unique_user["organization_id"],
        call_sid=sid2,
        extra={
            "voicemail": {
                "enabled": True,
                "message_url": url,
                "unknown_fallback": "voicemail",
            }
        },
    )
    r2 = _post_voice(client, call_sid=sid2, answered_by="unknown")
    assert "<Play>" in r2.text and url in r2.text


def test_call_flow_records_amd_result_on_row(
    client, unique_user, auth_headers, fake_twilio, monkeypatch
):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    sid = f"CA{uuid.uuid4().hex}"
    call_id = _seed_call(
        unique_user["organization_id"],
        call_sid=sid,
        extra={
            "voicemail": {
                "enabled": True,
                "message_url": "https://cdn.test/vm.mp3",
                "unknown_fallback": "human",
            }
        },
    )
    _post_voice(client, call_sid=sid, answered_by="machine_end_beep")

    db = SessionLocal()
    try:
        row = db.get(TelephonyCall, uuid.UUID(call_id))
        assert row.amd_result == "voicemail"
        assert row.voicemail_dropped is True
        assert row.voicemail_dropped_at is not None
        assert row.voicemail_recording_url == "https://cdn.test/vm.mp3"
        assert row.voicemail_detected_at is not None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Metrics aggregation
# --------------------------------------------------------------------------- #


def test_voicemail_metrics_aggregation(client, unique_user, auth_headers):
    org = unique_user["organization_id"]
    cid = _create_campaign(client, auth_headers)

    # 2 humans, 3 voicemails (2 dropped), and 1 voicemail retry child.
    _seed_call(org, campaign_id=cid, amd_result="human")
    _seed_call(org, campaign_id=cid, amd_result="human")
    parent = _seed_call(
        org, campaign_id=cid, amd_result="voicemail", voicemail_dropped=True
    )
    _seed_call(
        org, campaign_id=cid, amd_result="voicemail", voicemail_dropped=True
    )
    _seed_call(org, campaign_id=cid, amd_result="voicemail")
    _seed_call(org, campaign_id=cid, parent_call_id=parent)

    r = client.get(f"/api/v1/campaigns/{cid}/metrics", headers=auth_headers)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["human_answered"] == 2
    assert m["voicemail_detected"] == 3
    assert m["voicemail_dropped"] == 2
    assert m["voicemail_retry_count"] == 1
    assert m["voicemail_success_rate"] == pytest.approx(round(2 / 3, 3))


# --------------------------------------------------------------------------- #
# Retry engine: retry_on_voicemail
# --------------------------------------------------------------------------- #


def _seed_executable_campaign(client, headers, *, voicemail_config):
    # A playbook + a single-lead list so activation enqueues one execution.
    playbooks = client.get("/api/v1/playbooks", headers=headers).json()[
        "playbooks"
    ]
    playbook_id = playbooks[0]["id"]
    rows = [
        {
            "name": "VM Lead",
            "email": f"vm.{uuid.uuid4().hex[:6]}@example.com",
            "phone": "+14155557999",
            "company": "Acme",
        }
    ]
    ll = client.post(
        "/api/v1/leads/upload/commit",
        json={
            "rows": rows,
            "segmentation": {"tags": ["vm"]},
            "new_list_name": f"VM List {uuid.uuid4().hex[:6]}",
        },
        headers=headers,
    ).json()["lead_list"]["id"]

    cfg = {
        "name": f"VM Camp {uuid.uuid4().hex[:6]}",
        "playbook_id": playbook_id,
        "lead_list_id": ll,
        "schedule": {"start_immediately": True, "timezone": "UTC"},
        "business_hours": _WIDE_HOURS,
        "pacing": _UNLIMITED,
        "retry_config": {"max_attempts": 3, "retry_interval_minutes": 15},
        "voicemail_config": voicemail_config,
    }
    cid = client.post("/api/v1/campaigns", json=cfg, headers=headers).json()[
        "id"
    ]
    client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=headers,
    )
    return cid


def _voicemail_dispatch(db, executions):
    for ex in executions:
        wf = db.get(Workflow, ex.workflow_id)
        camp = db.get(Campaign, wf.campaign_id)
        ex.status = "running"
        db.commit()
        process_outcome(
            db,
            ex,
            "voicemail",
            retry_config=camp.retry_config,
            voicemail_config=camp.voicemail_config,
        )


def _only_execution(db, campaign_id) -> Execution:
    return (
        db.query(Execution)
        .join(Workflow, Workflow.id == Execution.workflow_id)
        .filter(Workflow.campaign_id == campaign_id)
        .one()
    )


def test_retry_on_voicemail_enabled_schedules_retry(client, auth_headers):
    cid = _seed_executable_campaign(
        client,
        auth_headers,
        voicemail_config={
            "voicemail_enabled": True,
            "voicemail_message_url": "https://cdn.test/vm.mp3",
            "retry_on_voicemail": True,
        },
    )
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        CampaignScheduler.tick(db, dispatcher=_voicemail_dispatch)
        ex = _only_execution(db, campaign.id)
        db.refresh(ex)
        assert ex.outcome == "voicemail"
        assert ex.retry_status == "scheduled"
        assert ex.attempt_number == 2
        db.refresh(campaign)
        assert campaign.status == CAMPAIGN_STATUS_ACTIVE
    finally:
        db.close()


def test_retry_on_voicemail_disabled_completes(client, auth_headers):
    cid = _seed_executable_campaign(
        client,
        auth_headers,
        voicemail_config={
            "voicemail_enabled": True,
            "voicemail_message_url": "https://cdn.test/vm.mp3",
            "retry_on_voicemail": False,
        },
    )
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        CampaignScheduler.tick(db, dispatcher=_voicemail_dispatch)
        ex = _only_execution(db, campaign.id)
        db.refresh(ex)
        assert ex.outcome == "voicemail"
        assert ex.status == "completed"
        assert ex.retry_status == "completed"
        # No pending retries -> next tick completes the campaign.
        CampaignScheduler.tick(db, dispatcher=_voicemail_dispatch)
        db.refresh(campaign)
        assert campaign.status == CAMPAIGN_STATUS_COMPLETED
    finally:
        db.close()
