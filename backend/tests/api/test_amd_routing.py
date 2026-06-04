"""Regression tests for the AMD / Voicemail-Drop runtime flow.

These cover the root causes found in the end-to-end audit:

* RC1 — when AMD / voicemail drop is requested, origination MUST go through
  Twilio (which runs Answering Machine Detection) even though a LiveKit SIP
  outbound trunk is configured. Routing AMD calls down the LiveKit-SIP path
  silently disables the whole feature.
* RC4 — voicemail playback success/failure is tracked from the terminal
  Twilio status callback.
* RC5 — a campaign-linked call's terminal outcome is reconciled back onto its
  execution (campaign → call → outcome → retry/metrics).
"""

from __future__ import annotations

import uuid

import pytest

from database.session import SessionLocal
from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.workflow_model import Workflow
from modules.telephony.model import TelephonyCall
from modules.telephony.service import TelephonyService
from tests._support.fakes import FakeLiveKitService, FakeTwilioClient


pytestmark = pytest.mark.api


class _NoopRegistry:
    """Agent registry stub — never spawns the orchestrator task."""

    def __init__(self) -> None:
        self.stopped: list[str] = []

    async def register(self, runner):
        return runner

    def get(self, call_id):
        return None

    async def stop(self, call_id, *, wait: bool = False, timeout: float = 5.0):
        self.stopped.append(call_id)


def _service() -> TelephonyService:
    return TelephonyService(
        twilio=FakeTwilioClient(),
        livekit=FakeLiveKitService(),
        agent_registry=_NoopRegistry(),
    )


# --------------------------------------------------------------------------- #
# RC1 — AMD-aware origination routing
# --------------------------------------------------------------------------- #


async def test_amd_call_uses_twilio_path_despite_sip_trunk(
    unique_user, monkeypatch
):
    """Voicemail enabled + SIP trunk configured -> Twilio originate w/ AMD."""

    monkeypatch.setattr(
        "modules.telephony.service.settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID",
        "ST_test_trunk",
    )
    monkeypatch.setattr(
        "modules.telephony.service.settings.LIVEKIT_SIP_URI", "sip.test.cloud"
    )
    monkeypatch.setattr(
        "modules.telephony.service.settings.TWILIO_AMD_ENABLED", True
    )

    svc = _service()
    row = await svc.initiate_outbound(
        to_number="+14155550123",
        organization_id=uuid.UUID(unique_user["organization_id"]),
        created_by=uuid.UUID(unique_user["user_id"]),
        voicemail_enabled=True,
        voicemail_message_url="https://cdn.test/vm.mp3",
    )

    # Twilio path taken: a Twilio call was originated with AMD requested...
    assert svc._twilio.calls_created, "expected Twilio create_call to run"
    assert svc._twilio.last_kwargs.get("answering_machine_detection") is True
    # ...and NOT the LiveKit-SIP origination path.
    assert (row.extra or {}).get("dial_mode") != "livekit_sip"


async def test_non_amd_call_uses_livekit_sip_path(unique_user, monkeypatch):
    """No AMD requested -> keep the preferred LiveKit-SIP origination path."""

    monkeypatch.setattr(
        "modules.telephony.service.settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID",
        "ST_test_trunk",
    )

    svc = _service()

    called: dict = {}

    async def _fake_sip(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(svc, "_run_livekit_sip_call", _fake_sip)

    row = await svc.initiate_outbound(
        to_number="+14155550123",
        organization_id=uuid.UUID(unique_user["organization_id"]),
        created_by=uuid.UUID(unique_user["user_id"]),
        voicemail_enabled=False,
    )

    # Let the scheduled background dial task run.
    import asyncio

    await asyncio.sleep(0.05)

    # LiveKit-SIP path taken, Twilio NOT used for origination.
    assert (row.extra or {}).get("dial_mode") == "livekit_sip"
    assert not svc._twilio.calls_created
    assert called.get("telephony_call_id") == row.id


# --------------------------------------------------------------------------- #
# RC4 — voicemail playback tracking via the status webhook
# --------------------------------------------------------------------------- #


def _seed_call(org_id, **kwargs) -> str:
    db = SessionLocal()
    try:
        row = TelephonyCall(
            organization_id=uuid.UUID(org_id),
            room_name=f"room-{uuid.uuid4().hex[:10]}",
            direction="outbound",
            from_number="+15557654321",
            to_number="+15550001234",
            **kwargs,
        )
        db.add(row)
        db.commit()
        return str(row.id)
    finally:
        db.close()


def _post_status(client, *, call_sid, status):
    return client.post(
        "/api/v1/telephony/webhooks/status",
        data={"CallSid": call_sid, "CallStatus": status, "CallDuration": "12"},
    )


def test_voicemail_playback_completed_tracked(
    client, unique_user, monkeypatch
):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    sid = f"CA{uuid.uuid4().hex}"
    call_id = _seed_call(
        unique_user["organization_id"],
        call_sid=sid,
        status="in-progress",
        amd_result="voicemail",
        voicemail_dropped=True,
        voicemail_recording_url="https://cdn.test/vm.mp3",
    )
    r = _post_status(client, call_sid=sid, status="completed")
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        row = db.get(TelephonyCall, uuid.UUID(call_id))
        playback = (row.extra or {}).get("voicemail_playback")
        assert playback and playback["status"] == "completed"
    finally:
        db.close()


def test_voicemail_playback_failed_tracked(client, unique_user, monkeypatch):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    sid = f"CA{uuid.uuid4().hex}"
    call_id = _seed_call(
        unique_user["organization_id"],
        call_sid=sid,
        status="in-progress",
        amd_result="voicemail",
        voicemail_dropped=True,
        voicemail_recording_url="https://cdn.test/vm.mp3",
    )
    r = _post_status(client, call_sid=sid, status="failed")
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        row = db.get(TelephonyCall, uuid.UUID(call_id))
        playback = (row.extra or {}).get("voicemail_playback")
        assert playback and playback["status"] == "failed"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# RC5 — campaign execution reconciliation from the terminal call status
# --------------------------------------------------------------------------- #


def _seed_execution(org_id, *, voicemail_config=None, retry_config=None):
    db = SessionLocal()
    try:
        campaign = Campaign(
            organization_id=uuid.UUID(org_id),
            name=f"Recon {uuid.uuid4().hex[:6]}",
            status="active",
            retry_config=retry_config
            or {"max_attempts": 3, "retry_interval_minutes": 15},
            voicemail_config=voicemail_config,
        )
        db.add(campaign)
        db.flush()
        wf = Workflow(campaign_id=campaign.id, state="active")
        db.add(wf)
        db.flush()
        ex = Execution(
            workflow_id=wf.id,
            status="running",
            attempt_number=1,
            retry_status="pending",
        )
        db.add(ex)
        db.commit()
        return str(ex.id)
    finally:
        db.close()


def test_reconcile_voicemail_outcome_on_completed(
    client, unique_user, monkeypatch
):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    org = unique_user["organization_id"]
    exec_id = _seed_execution(
        org,
        voicemail_config={
            "voicemail_enabled": True,
            "voicemail_message_url": "https://cdn.test/vm.mp3",
            "retry_on_voicemail": False,
        },
    )
    sid = f"CA{uuid.uuid4().hex}"
    _seed_call(
        org,
        call_sid=sid,
        status="in-progress",
        amd_result="voicemail",
        voicemail_dropped=True,
        extra={"campaign_execution_id": exec_id},
    )

    r = _post_status(client, call_sid=sid, status="completed")
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        ex = db.get(Execution, uuid.UUID(exec_id))
        assert ex.outcome == "voicemail"
        # retry_on_voicemail disabled -> terminal completed.
        assert ex.status == "completed"
    finally:
        db.close()


def test_reconcile_no_answer_outcome(client, unique_user, monkeypatch):
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )
    org = unique_user["organization_id"]
    exec_id = _seed_execution(org)
    sid = f"CA{uuid.uuid4().hex}"
    _seed_call(
        org,
        call_sid=sid,
        status="in-progress",
        extra={"campaign_execution_id": exec_id},
    )

    r = _post_status(client, call_sid=sid, status="no-answer")
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        ex = db.get(Execution, uuid.UUID(exec_id))
        assert ex.outcome == "no_answer"
    finally:
        db.close()
