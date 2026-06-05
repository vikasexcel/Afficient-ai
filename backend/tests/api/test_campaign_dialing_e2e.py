"""End-to-end proof that launching a campaign places a real outbound call.

Regression coverage for the campaign-execution audit:

* ROOT CAUSE — ``modules.campaign.worker._campaign_dial_context`` referenced
  ``campaign.created_by``, a column the ``Campaign`` model does not have. The
  resulting ``AttributeError`` was swallowed by ``run_execution``'s dial
  ``try/except``, so every activation silently fell back to the legacy
  LLM-plan stub and **no Twilio / LiveKit call was ever placed**.

These tests drive the real worker (``run_execution``) with a fake-backed
``TelephonyService`` (no live Twilio/LiveKit) and assert that:

1. ``TelephonyService.initiate_outbound`` is invoked for a queued lead.
2. A ``telephony_calls`` row is created and linked to the execution.
3. A Twilio Call SID is set (Twilio origination path).
4. A LiveKit-SIP call is originated when an outbound trunk is configured.
5. The terminal Twilio status webhook reconciles the execution outcome and
   advances campaign metrics (campaign -> call -> outcome -> metrics).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from database.session import SessionLocal
from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.workflow_model import Workflow
from modules.livekit.exceptions import LiveKitError
from modules.telephony.exceptions import TwilioProviderError
from modules.telephony.model import TelephonyCall
from modules.telephony.service import TelephonyService
from tests._support.fakes import FakeLiveKitService, FakeTwilioClient


pytestmark = pytest.mark.api


_WIDE_HOURS = {
    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "start": "00:00",
    "end": "23:59",
    "skip_holidays": False,
}


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


def _fake_service() -> TelephonyService:
    return TelephonyService(
        twilio=FakeTwilioClient(),
        livekit=FakeLiveKitService(),
        agent_registry=_NoopRegistry(),
    )


def _seed_playbook(client, headers) -> str:
    r = client.get("/api/v1/playbooks", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["playbooks"][0]["id"]


def _seed_lead_list(client, headers) -> str:
    list_name = f"Dial List {uuid.uuid4().hex[:6]}"
    rows = [
        {
            "name": "Ada Lovelace",
            "email": f"ada.{uuid.uuid4().hex[:5]}@example.com",
            "phone": "+14155550199",
            "company": "Acme",
        }
    ]
    r = client.post(
        "/api/v1/leads/upload/commit",
        json={
            "rows": rows,
            "segmentation": {"tags": ["dial"]},
            "new_list_name": list_name,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["lead_list"]["id"]


def _launch_campaign(client, headers) -> str:
    playbook_id = _seed_playbook(client, headers)
    lead_list_id = _seed_lead_list(client, headers)
    cid = client.post(
        "/api/v1/campaigns",
        json={
            "name": f"Dial {uuid.uuid4().hex[:6]}",
            "playbook_id": playbook_id,
            "lead_list_id": lead_list_id,
            "schedule": {"start_immediately": True, "timezone": "UTC"},
            "business_hours": _WIDE_HOURS,
        },
        headers=headers,
    ).json()["id"]

    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["enqueued_leads"] == 1, r.json()
    return cid


def _queued_execution(campaign_id: str) -> uuid.UUID:
    """Return the id of the single queued execution for a campaign."""

    db = SessionLocal()
    try:
        row = (
            db.query(Execution)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .filter(Workflow.campaign_id == uuid.UUID(campaign_id))
            .filter(Execution.status == "queued")
            .first()
        )
        assert row is not None, "expected a queued execution after activation"
        return row.id
    finally:
        db.close()


async def _run_worker(execution_id: uuid.UUID):
    from modules.campaign.worker import run_execution

    db = SessionLocal()
    try:
        execution = db.get(Execution, execution_id)
        await run_execution(db, execution)
        db.refresh(execution)
        db.expunge(execution)
        return execution
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Twilio origination path  (no SIP trunk -> Twilio create_call)
# --------------------------------------------------------------------------- #


async def test_launch_places_real_twilio_call_to_lead(
    client, unique_user, monkeypatch
):
    headers = {"Authorization": f"Bearer {unique_user['access_token']}"}
    campaign_id = _launch_campaign(client, headers)
    execution_id = _queued_execution(campaign_id)

    svc = _fake_service()
    monkeypatch.setattr(
        "modules.telephony.dependencies.get_telephony_service",
        lambda: svc,
    )
    # Master switch on; force the Twilio origination path (no SIP trunk).
    monkeypatch.setattr(
        "modules.campaign.worker.settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "modules.telephony.service.settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID",
        "",
    )

    execution = await _run_worker(execution_id)

    # 1. The worker dialed instead of running the LLM stub: execution is left
    #    ``running`` (terminal outcome arrives later via the status webhook).
    assert execution.status == "running"
    assert (execution.context or {}).get("telephony_call_id")

    # 2. TelephonyService.initiate_outbound -> Twilio create_call actually ran.
    assert svc._twilio.calls_created, "expected a real Twilio origination"

    # 3. A telephony_calls row exists, linked to the lead + campaign + exec,
    #    with a Twilio Call SID set.
    db = SessionLocal()
    try:
        call = (
            db.query(TelephonyCall)
            .filter(
                TelephonyCall.campaign_id == uuid.UUID(campaign_id)
            )
            .first()
        )
        assert call is not None, "telephony_calls not populated"
        assert call.call_sid and call.call_sid.startswith("CA")
        assert call.to_number == "+14155550199"
        assert (call.extra or {}).get("campaign_execution_id") == str(
            execution_id
        )
        call_sid = call.call_sid
    finally:
        db.close()

    # 4. Drive the terminal Twilio status webhook -> outcome reconciliation.
    await svc.handle_status_webhook(
        params={
            "CallSid": call_sid,
            "CallStatus": "completed",
            "CallDuration": "42",
        }
    )

    db = SessionLocal()
    try:
        ex = db.get(Execution, execution_id)
        assert ex.outcome == "completed"
        assert ex.status == "completed"
    finally:
        db.close()

    # 5. Campaign metrics advanced off the reconciled call.
    m = client.get(
        f"/api/v1/campaigns/{campaign_id}/metrics", headers=headers
    ).json()
    assert m["completed_calls"] == 1, m


# --------------------------------------------------------------------------- #
# LiveKit-SIP origination path  (outbound trunk configured, no AMD)
# --------------------------------------------------------------------------- #


async def test_launch_places_real_livekit_sip_call(
    client, unique_user, monkeypatch
):
    headers = {"Authorization": f"Bearer {unique_user['access_token']}"}
    campaign_id = _launch_campaign(client, headers)
    execution_id = _queued_execution(campaign_id)

    svc = _fake_service()
    monkeypatch.setattr(
        "modules.telephony.dependencies.get_telephony_service",
        lambda: svc,
    )
    monkeypatch.setattr(
        "modules.campaign.worker.settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED",
        True,
    )
    # Outbound trunk set + no AMD -> the LiveKit-SIP origination path.
    monkeypatch.setattr(
        "modules.telephony.service.settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID",
        "ST_test_trunk",
    )

    sip_calls: dict = {}

    async def _fake_sip(**kwargs):
        sip_calls.update(kwargs)

    monkeypatch.setattr(svc, "_run_livekit_sip_call", _fake_sip)

    execution = await _run_worker(execution_id)

    # Let the scheduled background LiveKit-SIP dial task run.
    await asyncio.sleep(0.05)

    # The execution dialed (running) and a LiveKit-SIP leg was originated.
    assert execution.status == "running"
    assert sip_calls.get("to_number") == "+14155550199"

    db = SessionLocal()
    try:
        call = (
            db.query(TelephonyCall)
            .filter(TelephonyCall.campaign_id == uuid.UUID(campaign_id))
            .first()
        )
        assert call is not None, "telephony_calls not populated"
        assert (call.extra or {}).get("dial_mode") == "livekit_sip"
        assert sip_calls.get("telephony_call_id") == call.id
        # Twilio was NOT used for origination on the SIP path.
        assert not svc._twilio.calls_created
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Dial-failure handling — NO silent LLM fallback
# --------------------------------------------------------------------------- #


class _RaisingService:
    """Telephony service stub whose origination always raises."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    async def initiate_outbound(self, **_kwargs):
        self.calls += 1
        raise self._exc


def _seed_dial_execution(
    client, headers, org_id, *, phone, retry_config=None
):
    """Seed an active campaign + workflow + a queued lead execution.

    Lets the test control the lead phone (incl. an empty/invalid one) and the
    campaign retry policy. Uses a real seeded playbook so the campaign's
    ``playbook_id`` FK is valid.
    """

    playbook_id = _seed_playbook(client, headers)
    db = SessionLocal()
    try:
        campaign = Campaign(
            organization_id=uuid.UUID(org_id),
            name=f"Fail {uuid.uuid4().hex[:6]}",
            status="active",
            playbook_id=uuid.UUID(playbook_id),
            retry_config=retry_config,
        )
        db.add(campaign)
        db.flush()
        wf = Workflow(campaign_id=campaign.id, state="active")
        db.add(wf)
        db.flush()
        ex = Execution(
            workflow_id=wf.id,
            status="queued",
            attempt_number=1,
            retry_status="pending",
            context={
                "campaign_id": str(campaign.id),
                "playbook_id": playbook_id,
                "lead": {
                    "id": str(uuid.uuid4()),
                    "name": "Ada Lovelace",
                    "phone": phone,
                },
            },
        )
        db.add(ex)
        db.commit()
        return str(campaign.id), ex.id
    finally:
        db.close()


def _enable_dialing(monkeypatch):
    monkeypatch.setattr(
        "modules.campaign.worker.settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED",
        True,
    )


async def test_dial_telephony_unavailable_fails_execution(
    client, unique_user, monkeypatch
):
    """Telephony singleton unavailable -> execution failed, NO LLM fallback."""

    headers = {"Authorization": f"Bearer {unique_user['access_token']}"}
    # No retry_config -> terminal failure (no retry scheduled).
    campaign_id, exec_id = _seed_dial_execution(
        client, headers, unique_user["organization_id"], phone="+14155550123"
    )

    def _boom():
        raise RuntimeError("twilio creds missing")

    monkeypatch.setattr(
        "modules.telephony.dependencies.get_telephony_service", _boom
    )
    # Guard against any LLM fallback being attempted.
    monkeypatch.setattr(
        "modules.campaign.worker.get_openai",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not run")),
    )
    _enable_dialing(monkeypatch)

    await _run_worker(exec_id)

    db = SessionLocal()
    try:
        ex = db.get(Execution, exec_id)
        assert ex.status == "failed"
        assert ex.retry_status is None  # no retry_config -> terminal
        assert ex.outcome == "failed"
        assert "telephony unavailable" in (ex.last_failure_reason or "")
        # No silent completion: the LLM stub never ran, so no output.
        assert ex.output is None
    finally:
        db.close()

    m = client.get(
        f"/api/v1/campaigns/{campaign_id}/metrics", headers=headers
    ).json()
    assert m["failed_calls"] == 1, m
    assert m["failed_executions"] == 1, m
    assert m["completed_calls"] == 0, m


async def test_dial_twilio_failure_schedules_retry(
    client, unique_user, monkeypatch
):
    """Twilio origination raises + retry configured -> retry scheduled."""

    headers = {"Authorization": f"Bearer {unique_user['access_token']}"}
    campaign_id, exec_id = _seed_dial_execution(
        client,
        headers,
        unique_user["organization_id"],
        phone="+14155550123",
        retry_config={"max_attempts": 3, "retry_interval_minutes": 15},
    )

    svc = _RaisingService(
        TwilioProviderError("twilio.calls.create failed (21211): bad number")
    )
    monkeypatch.setattr(
        "modules.telephony.dependencies.get_telephony_service", lambda: svc
    )
    monkeypatch.setattr(
        "modules.campaign.worker.get_openai",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not run")),
    )
    _enable_dialing(monkeypatch)

    await _run_worker(exec_id)

    assert svc.calls == 1, "initiate_outbound should have been attempted"

    db = SessionLocal()
    try:
        ex = db.get(Execution, exec_id)
        # Retryable failure with attempts remaining -> scheduled retry.
        assert ex.status == "failed"
        assert ex.retry_status == "scheduled"
        assert ex.next_retry_at is not None
        assert ex.attempt_number == 2
        assert ex.outcome == "failed"
        assert "dial failed" in (ex.last_failure_reason or "")
        assert ex.output is None  # no silent LLM completion
    finally:
        db.close()

    m = client.get(
        f"/api/v1/campaigns/{campaign_id}/metrics", headers=headers
    ).json()
    # Row is parked for retry: counts as a failed *call* but not a terminal
    # failed *execution* yet.
    assert m["failed_calls"] == 1, m
    assert m["failed_executions"] == 0, m


async def test_dial_livekit_failure_fails_execution(
    client, unique_user, monkeypatch
):
    """LiveKit origination raises + no retry -> terminal failed, NO LLM."""

    headers = {"Authorization": f"Bearer {unique_user['access_token']}"}
    campaign_id, exec_id = _seed_dial_execution(
        client, headers, unique_user["organization_id"], phone="+14155550123"
    )

    svc = _RaisingService(LiveKitError("SIP gateway unreachable"))
    monkeypatch.setattr(
        "modules.telephony.dependencies.get_telephony_service", lambda: svc
    )
    monkeypatch.setattr(
        "modules.campaign.worker.get_openai",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not run")),
    )
    _enable_dialing(monkeypatch)

    await _run_worker(exec_id)

    assert svc.calls == 1
    db = SessionLocal()
    try:
        ex = db.get(Execution, exec_id)
        assert ex.status == "failed"
        assert ex.retry_status is None
        assert ex.outcome == "failed"
        assert ex.output is None
    finally:
        db.close()

    m = client.get(
        f"/api/v1/campaigns/{campaign_id}/metrics", headers=headers
    ).json()
    assert m["failed_executions"] == 1, m


async def test_dial_invalid_phone_fails_execution(
    client, unique_user, monkeypatch
):
    """Lead has no/invalid phone -> dial fails (retry if configured), NO LLM."""

    headers = {"Authorization": f"Bearer {unique_user['access_token']}"}
    campaign_id, exec_id = _seed_dial_execution(
        client,
        headers,
        unique_user["organization_id"],
        phone="",  # invalid / missing
        retry_config={"max_attempts": 2, "retry_interval_minutes": 10},
    )

    # Telephony must never be reached for an undiallable lead.
    def _boom():
        raise AssertionError("telephony must not be called for invalid phone")

    monkeypatch.setattr(
        "modules.telephony.dependencies.get_telephony_service", _boom
    )
    monkeypatch.setattr(
        "modules.campaign.worker.get_openai",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not run")),
    )
    _enable_dialing(monkeypatch)

    await _run_worker(exec_id)

    db = SessionLocal()
    try:
        ex = db.get(Execution, exec_id)
        assert ex.status == "failed"
        # retry configured (2 attempts) -> a retry is scheduled.
        assert ex.retry_status == "scheduled"
        assert ex.attempt_number == 2
        assert "missing lead phone" in (ex.last_failure_reason or "")
        assert ex.output is None
    finally:
        db.close()

    # No telephony_calls row was created for an undiallable lead.
    db = SessionLocal()
    try:
        call = (
            db.query(TelephonyCall)
            .filter(TelephonyCall.campaign_id == uuid.UUID(campaign_id))
            .first()
        )
        assert call is None
    finally:
        db.close()
