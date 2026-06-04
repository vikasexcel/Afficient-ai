"""End-to-end coverage for the automatic call-scheduling engine.

Exercises the :class:`CampaignScheduler` tick (auto-activation, paced
dispatch, completion, manual pause/resume) plus the new schedule-status /
metrics endpoints. The tick is driven directly with an injected dispatcher
so no Celery broker or OpenAI access is required.
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
    CAMPAIGN_STATUS_PAUSED,
    CAMPAIGN_STATUS_SCHEDULED,
    Campaign,
)
from modules.campaign.scheduler import CampaignScheduler
from modules.campaign.scheduling import _WEEKDAY_IDS
from modules.campaign.workflow_model import Workflow


pytestmark = pytest.mark.api


# --------------------------------------------------------------------------- #
# Setup helpers (mirror tests/api/test_campaign_e2e.py)
# --------------------------------------------------------------------------- #


def _seed_playbook(client, headers) -> str:
    r = client.get("/api/v1/playbooks", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["playbooks"][0]["id"]


def _seed_lead_list(client, headers, n: int) -> tuple[str, int]:
    list_name = f"Sched List {uuid.uuid4().hex[:6]}"
    rows = [
        {
            "name": f"Lead {i}",
            "email": f"lead{i}.{uuid.uuid4().hex[:5]}@example.com",
            "phone": f"+1415556{2000 + i:04d}",
            "company": "Acme",
        }
        for i in range(n)
    ]
    r = client.post(
        "/api/v1/leads/upload/commit",
        json={
            "rows": rows,
            "segmentation": {"tags": ["sched"]},
            "new_list_name": list_name,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["lead_list"]["id"], body["inserted"]


_WIDE_HOURS = {
    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "start": "00:00",
    "end": "23:59",
    "skip_holidays": False,
}


def _create_campaign(client, headers, *, n_leads=3, pacing=None, name=None):
    playbook_id = _seed_playbook(client, headers)
    lead_list_id, inserted = _seed_lead_list(client, headers, n_leads)
    cfg = {
        "name": name or f"Sched {uuid.uuid4().hex[:6]}",
        "playbook_id": playbook_id,
        "lead_list_id": lead_list_id,
        "schedule": {"start_immediately": True, "timezone": "UTC"},
        "business_hours": _WIDE_HOURS,
    }
    if pacing is not None:
        cfg["pacing"] = pacing
    cid = client.post(
        "/api/v1/campaigns", json=cfg, headers=headers
    ).json()["id"]
    return cid, inserted


def _noop_dispatch(db, executions):
    """Leave executions queued (verifies activation/enqueue in isolation)."""


def _complete_dispatch(db, executions):
    for ex in executions:
        ex.status = "completed"
        ex.output = "ok"
    db.commit()


def _exec_counts(db, campaign_id):
    rows = (
        db.query(Execution.status, Execution)
        .join(Workflow, Workflow.id == Execution.workflow_id)
        .filter(Workflow.campaign_id == campaign_id)
        .all()
    )
    counts: dict[str, int] = {}
    for status, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# Auto-activation
# --------------------------------------------------------------------------- #


def test_tick_auto_activates_due_scheduled_campaign(client, auth_headers):
    cid, inserted = _create_campaign(client, auth_headers, n_leads=3)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        # Pretend the user scheduled it for one minute ago, business hours open.
        campaign.status = CAMPAIGN_STATUS_SCHEDULED
        campaign.scheduled_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()

        CampaignScheduler.tick(db, dispatcher=_noop_dispatch)
        db.refresh(campaign)

        assert campaign.status == CAMPAIGN_STATUS_ACTIVE
        workflow = (
            db.query(Workflow)
            .filter(Workflow.campaign_id == campaign.id)
            .first()
        )
        assert workflow is not None
        counts = _exec_counts(db, campaign.id)
        assert counts.get("queued", 0) == inserted
    finally:
        db.close()


def test_tick_does_not_activate_future_campaign(client, auth_headers):
    cid, _ = _create_campaign(client, auth_headers, n_leads=2)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        campaign.status = CAMPAIGN_STATUS_SCHEDULED
        campaign.scheduled_at = datetime.utcnow() + timedelta(days=3650)
        db.commit()

        CampaignScheduler.tick(db, dispatcher=_noop_dispatch)
        db.refresh(campaign)

        assert campaign.status == CAMPAIGN_STATUS_SCHEDULED
        assert (
            db.query(Workflow)
            .filter(Workflow.campaign_id == campaign.id)
            .first()
            is None
        )
    finally:
        db.close()


def test_tick_defers_outside_business_hours(client, auth_headers):
    cid, _ = _create_campaign(client, auth_headers, n_leads=2)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        # Restrict to a weekday that is NOT today so "now" is outside hours.
        today_id = _WEEKDAY_IDS[datetime.utcnow().weekday()]
        other = next(d for d in _WEEKDAY_IDS if d != today_id)
        campaign.status = CAMPAIGN_STATUS_SCHEDULED
        campaign.scheduled_at = datetime.utcnow() - timedelta(minutes=1)
        campaign.business_hours = {
            "days": [other],
            "start": "00:00",
            "end": "23:59",
        }
        db.commit()

        CampaignScheduler.tick(db, dispatcher=_noop_dispatch)
        db.refresh(campaign)

        # Deferred: still scheduled, no workflow created yet.
        assert campaign.status == CAMPAIGN_STATUS_SCHEDULED
        assert (
            db.query(Workflow)
            .filter(Workflow.campaign_id == campaign.id)
            .first()
            is None
        )
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Pacing
# --------------------------------------------------------------------------- #


def test_tick_respects_pacing_rate(client, auth_headers):
    # 120 calls/hour over a 60s tick == 2 dispatches per tick.
    cid, inserted = _create_campaign(
        client,
        auth_headers,
        n_leads=5,
        pacing={"calls_per_hour": 120, "max_concurrent_calls": 0},
    )
    # Activate now (wide hours, immediate) -> 5 queued executions.
    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    )
    assert r.json()["state"] == "active"

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        CampaignScheduler.tick(db, dispatcher=_complete_dispatch)
        counts = _exec_counts(db, campaign.id)
        # Exactly 2 dispatched this tick, the rest still queued.
        assert counts.get("completed", 0) == 2
        assert counts.get("queued", 0) == inserted - 2
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Completion + status transitions
# --------------------------------------------------------------------------- #


def test_tick_completes_when_all_executions_terminal(client, auth_headers):
    cid, _ = _create_campaign(client, auth_headers, n_leads=2)
    client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        # Mark every execution done, then tick.
        execs = (
            db.query(Execution)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .filter(Workflow.campaign_id == campaign.id)
            .all()
        )
        for ex in execs:
            ex.status = "completed"
        db.commit()

        CampaignScheduler.tick(db, dispatcher=_noop_dispatch)
        db.refresh(campaign)
        assert campaign.status == CAMPAIGN_STATUS_COMPLETED

        workflow = (
            db.query(Workflow)
            .filter(Workflow.campaign_id == campaign.id)
            .first()
        )
        assert workflow.state == "completed"
    finally:
        db.close()


def test_pause_resume_transitions_and_scheduler_skips_paused(
    client, auth_headers
):
    cid, inserted = _create_campaign(client, auth_headers, n_leads=3)
    client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    )

    # active -> paused
    p = client.post(
        f"/api/v1/campaigns/{cid}/pause", headers=auth_headers
    )
    assert p.status_code == 200, p.text
    assert p.json()["status"] == CAMPAIGN_STATUS_PAUSED

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        # A tick must NOT dispatch a paused campaign.
        CampaignScheduler.tick(db, dispatcher=_complete_dispatch)
        counts = _exec_counts(db, campaign.id)
        assert counts.get("queued", 0) == inserted
        assert counts.get("completed", 0) == 0
    finally:
        db.close()

    # paused -> active
    res = client.post(
        f"/api/v1/campaigns/{cid}/resume", headers=auth_headers
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == CAMPAIGN_STATUS_ACTIVE


def test_pause_rejects_non_active(client, auth_headers):
    cid, _ = _create_campaign(client, auth_headers, n_leads=1)
    # Still a draft -> cannot pause.
    r = client.post(f"/api/v1/campaigns/{cid}/pause", headers=auth_headers)
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# API: schedule-status + metrics
# --------------------------------------------------------------------------- #


def test_schedule_status_endpoint(client, auth_headers):
    cid, _ = _create_campaign(
        client,
        auth_headers,
        n_leads=2,
        pacing={"calls_per_hour": 90, "max_concurrent_calls": 4},
    )
    r = client.get(
        f"/api/v1/campaigns/{cid}/schedule-status", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_due"] is True  # start_immediately -> no scheduled_at
    assert body["within_business_hours"] is True
    assert body["pacing"]["calls_per_hour"] == 90
    assert body["pacing"]["max_concurrent_calls"] == 4
    assert "next_business_window" in body


def test_metrics_endpoint(client, auth_headers):
    cid, inserted = _create_campaign(client, auth_headers, n_leads=4)
    client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    )

    # Mark half the leads completed to exercise progress math.
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, uuid.UUID(cid))
        execs = (
            db.query(Execution)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .filter(Workflow.campaign_id == campaign.id)
            .all()
        )
        for ex in execs[:2]:
            ex.status = "completed"
        db.commit()
    finally:
        db.close()

    r = client.get(
        f"/api/v1/campaigns/{cid}/metrics", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_leads"] == inserted
    assert body["completed_calls"] == 2
    assert body["queued_leads"] == inserted - 2
    assert body["progress_percent"] == pytest.approx(50.0)
