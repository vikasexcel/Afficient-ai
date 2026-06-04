"""End-to-end coverage for the Retry Execution Engine.

Drives the :class:`CampaignScheduler` tick directly with injected dispatchers
that route call outcomes through ``process_outcome`` (no Celery / OpenAI /
telephony required). Verifies retry scheduling, requeue + execution, max-attempt
exhaustion, successful retries, business-hours retry deferral, completion gating
while retries are pending, and the new retry APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

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
from modules.campaign.scheduling import _WEEKDAY_IDS
from modules.campaign.workflow_model import Workflow


pytestmark = pytest.mark.api


# --------------------------------------------------------------------------- #
# Setup helpers (mirror tests/api/test_campaign_scheduler_e2e.py)
# --------------------------------------------------------------------------- #


_WIDE_HOURS = {
    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "start": "00:00",
    "end": "23:59",
    "skip_holidays": False,
}

# Unlimited pacing so retries dispatch immediately and tests stay deterministic.
_UNLIMITED = {"calls_per_hour": 0, "max_concurrent_calls": 0}


def _seed_playbook(client, headers) -> str:
    r = client.get("/api/v1/playbooks", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["playbooks"][0]["id"]


def _seed_lead_list(client, headers, n: int) -> tuple[str, int]:
    list_name = f"Retry List {uuid.uuid4().hex[:6]}"
    rows = [
        {
            "name": f"Lead {i}",
            "email": f"lead{i}.{uuid.uuid4().hex[:5]}@example.com",
            "phone": f"+1415557{3000 + i:04d}",
            "company": "Acme",
        }
        for i in range(n)
    ]
    r = client.post(
        "/api/v1/leads/upload/commit",
        json={
            "rows": rows,
            "segmentation": {"tags": ["retry"]},
            "new_list_name": list_name,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["lead_list"]["id"], body["inserted"]


def _create_campaign(
    client,
    headers,
    *,
    n_leads=1,
    retry_config=None,
    business_hours=None,
):
    playbook_id = _seed_playbook(client, headers)
    lead_list_id, inserted = _seed_lead_list(client, headers, n_leads)
    cfg = {
        "name": f"Retry {uuid.uuid4().hex[:6]}",
        "playbook_id": playbook_id,
        "lead_list_id": lead_list_id,
        "schedule": {"start_immediately": True, "timezone": "UTC"},
        "business_hours": business_hours or _WIDE_HOURS,
        "pacing": _UNLIMITED,
    }
    if retry_config is not None:
        cfg["retry_config"] = retry_config
    cid = client.post(
        "/api/v1/campaigns", json=cfg, headers=headers
    ).json()["id"]
    return cid, inserted


def _activate(client, headers, cid):
    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=headers,
    )
    assert r.json()["state"] == "active", r.text


def _outcome_dispatch(outcome: str):
    """A dispatcher that runs each execution to the given call ``outcome``."""

    def _dispatch(db, executions):
        for ex in executions:
            wf = db.get(Workflow, ex.workflow_id)
            camp = db.get(Campaign, wf.campaign_id)
            ex.status = "running"
            db.commit()
            process_outcome(db, ex, outcome, retry_config=camp.retry_config)

    return _dispatch


def _only_execution(db, campaign_id) -> Execution:
    return (
        db.query(Execution)
        .join(Workflow, Workflow.id == Execution.workflow_id)
        .filter(Workflow.campaign_id == campaign_id)
        .one()
    )


# --------------------------------------------------------------------------- #
# Retry scheduling
# --------------------------------------------------------------------------- #


def test_failed_call_schedules_retry(client, auth_headers):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=1,
        retry_config={
            "max_attempts": 3,
            "retry_interval_minutes": 15,
            "backoff_strategy": "fixed",
        },
    )
    _activate(client, auth_headers, cid)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        before = datetime.utcnow()
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("no_answer"))

        ex = _only_execution(db, campaign.id)
        db.refresh(ex)
        assert ex.status == "failed"
        assert ex.retry_status == "scheduled"
        assert ex.attempt_number == 2
        assert ex.outcome == "no_answer"
        assert ex.next_retry_at is not None
        # Fixed 15-minute backoff into the future.
        assert ex.next_retry_at >= before + timedelta(minutes=14)

        # A scheduled retry must NOT flip the campaign to completed.
        db.refresh(campaign)
        assert campaign.status == CAMPAIGN_STATUS_ACTIVE
    finally:
        db.close()


def test_scheduler_does_not_complete_while_retry_pending(client, auth_headers):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=1,
        retry_config={"max_attempts": 3, "retry_interval_minutes": 15},
    )
    _activate(client, auth_headers, cid)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        # First tick: fail -> schedule a *future* retry.
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("busy"))
        # Second tick: retry not due yet -> stay active, not completed.
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("busy"))
        db.refresh(campaign)
        assert campaign.status == CAMPAIGN_STATUS_ACTIVE
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Retry execution (requeue when due)
# --------------------------------------------------------------------------- #


def test_due_retry_is_requeued_and_executed(client, auth_headers):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=1,
        retry_config={"max_attempts": 3, "retry_interval_minutes": 15},
    )
    _activate(client, auth_headers, cid)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        # Attempt 1 fails -> scheduled.
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("no_answer"))
        ex = _only_execution(db, campaign.id)
        assert ex.retry_status == "scheduled"

        # Make the retry due now.
        ex.next_retry_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

        # Attempt 2 succeeds -> requeued, dispatched, completed.
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("qualified"))
        db.refresh(ex)
        assert ex.status == "completed"
        assert ex.retry_status == "completed"
        assert ex.outcome == "qualified"
        assert ex.attempt_number == 2
    finally:
        db.close()


def test_business_hours_defer_due_retry(client, auth_headers):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=1,
        retry_config={"max_attempts": 3, "retry_interval_minutes": 15},
    )
    _activate(client, auth_headers, cid)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("no_answer"))
        ex = _only_execution(db, campaign.id)
        assert ex.retry_status == "scheduled"

        # Retry is due, but restrict business hours to a different weekday so
        # "now" is outside the calling window.
        today_id = _WEEKDAY_IDS[datetime.utcnow().weekday()]
        other = next(d for d in _WEEKDAY_IDS if d != today_id)
        campaign.business_hours = {
            "days": [other],
            "start": "00:00",
            "end": "23:59",
        }
        ex.next_retry_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("qualified"))
        db.refresh(ex)
        # Still parked — business hours deferred the requeue.
        assert ex.retry_status == "scheduled"
        assert ex.status == "failed"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Max attempts / exhaustion
# --------------------------------------------------------------------------- #


def test_max_attempts_enforced_then_exhausted(client, auth_headers):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=1,
        retry_config={"max_attempts": 2, "retry_interval_minutes": 15},
    )
    _activate(client, auth_headers, cid)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))

        # Attempt 1 fails -> scheduled (attempt_number -> 2).
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("no_answer"))
        ex = _only_execution(db, campaign.id)
        assert ex.retry_status == "scheduled"
        assert ex.attempt_number == 2

        # Force the retry due, attempt 2 fails -> exhausted (hit max_attempts).
        ex.next_retry_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("no_answer"))
        db.refresh(ex)
        assert ex.retry_status == "exhausted"
        assert ex.next_retry_at is None
        assert ex.attempt_number == 2
        assert ex.status == "failed"

        # No retries pending -> next tick completes the campaign.
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("no_answer"))
        db.refresh(campaign)
        assert campaign.status == CAMPAIGN_STATUS_COMPLETED
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Exponential backoff end-to-end
# --------------------------------------------------------------------------- #


def test_exponential_backoff_spacing(client, auth_headers):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=1,
        retry_config={
            "max_attempts": 5,
            "retry_interval_minutes": 15,
            "backoff_strategy": "exponential",
        },
    )
    _activate(client, auth_headers, cid)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))

        # Attempt 1 fails -> ~15 min out.
        t0 = datetime.utcnow()
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("busy"))
        ex = _only_execution(db, campaign.id)
        gap1 = (ex.next_retry_at - t0).total_seconds() / 60.0
        assert 14 <= gap1 <= 16

        # Force due, attempt 2 fails -> ~30 min out.
        ex.next_retry_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        t1 = datetime.utcnow()
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("busy"))
        db.refresh(ex)
        gap2 = (ex.next_retry_at - t1).total_seconds() / 60.0
        assert 29 <= gap2 <= 31
        assert ex.attempt_number == 3
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# APIs + metrics
# --------------------------------------------------------------------------- #


def test_retries_and_metrics_endpoints_for_successful_retry(
    client, auth_headers
):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=1,
        retry_config={"max_attempts": 3, "retry_interval_minutes": 15},
    )
    _activate(client, auth_headers, cid)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("no_answer"))
        ex = _only_execution(db, campaign.id)
        ex.next_retry_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("qualified"))
        exec_id = str(ex.id)
    finally:
        db.close()

    # /retries summary
    r = client.get(f"/api/v1/campaigns/{cid}/retries", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_retries"] == 1
    assert body["pending_retries"] == 0
    assert body["exhausted_retries"] == 0
    assert body["successful_retries"] == 1

    # /metrics retry fields
    m = client.get(f"/api/v1/campaigns/{cid}/metrics", headers=auth_headers)
    assert m.status_code == 200, m.text
    mb = m.json()
    assert mb["retry_count"] == 1
    assert mb["exhausted_retries"] == 0
    assert mb["retry_success_rate"] == pytest.approx(1.0)
    assert mb["average_attempts_per_call"] == pytest.approx(2.0)

    # /executions/{id}/retry-history
    h = client.get(
        f"/api/v1/campaigns/executions/{exec_id}/retry-history",
        headers=auth_headers,
    )
    assert h.status_code == 200, h.text
    hb = h.json()
    assert hb["attempt_number"] == 2
    assert hb["retry_status"] == "completed"
    assert len(hb["attempts"]) == 2
    assert hb["attempts"][0]["attempt_number"] == 1
    assert hb["attempts"][0]["outcome"] == "no_answer"
    assert hb["attempts"][1]["outcome"] == "qualified"


def test_retries_endpoint_reports_exhausted(client, auth_headers):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=1,
        retry_config={"max_attempts": 1, "retry_interval_minutes": 15},
    )
    _activate(client, auth_headers, cid)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        # max_attempts=1 -> first failure exhausts immediately.
        CampaignScheduler.tick(db, dispatcher=_outcome_dispatch("no_answer"))
        ex = _only_execution(db, campaign.id)
        db.refresh(ex)
        assert ex.retry_status == "exhausted"
    finally:
        db.close()

    r = client.get(f"/api/v1/campaigns/{cid}/retries", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exhausted_retries"] == 1
    assert body["successful_retries"] == 0
    assert body["pending_retries"] == 0
