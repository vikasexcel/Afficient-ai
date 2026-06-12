from __future__ import annotations

import uuid
from types import SimpleNamespace

from modules.campaign.model import Campaign
from modules.campaign.worker import _build_dial_payload, _campaign_dial_context
from modules.campaign.workflow_model import Workflow


def _fake_db(*, campaign_timezone: str | None = "Asia/Kolkata"):
    workflow_id = uuid.uuid4()
    campaign_id = uuid.uuid4()
    playbook_id = uuid.uuid4()
    org_id = uuid.uuid4()

    workflow = SimpleNamespace(id=workflow_id, campaign_id=campaign_id)
    campaign = SimpleNamespace(
        id=campaign_id,
        organization_id=org_id,
        playbook_id=playbook_id,
        timezone=campaign_timezone,
    )

    class FakeDb:
        def get(self, model, row_id):
            if model is Workflow and row_id == workflow_id:
                return workflow
            if model is Campaign and row_id == campaign_id:
                return campaign
            return None

    return FakeDb(), workflow, campaign


def _execution(workflow_id: uuid.UUID, lead: dict):
    return SimpleNamespace(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
        context={"lead": lead},
    )


def test_campaign_dial_context_uses_campaign_timezone_when_lead_has_none():
    db, workflow, _campaign = _fake_db(campaign_timezone="Asia/Kolkata")
    execution = _execution(
        workflow.id,
        {
            "id": str(uuid.uuid4()),
            "name": "Ada Lovelace",
            "phone": "+14155550199",
            "email": "ada@example.com",
        },
    )

    dial = _campaign_dial_context(db, execution)

    assert dial is not None
    assert dial["timezone"] == "Asia/Kolkata"


def test_campaign_dial_context_prefers_lead_timezone_over_campaign_timezone():
    db, workflow, _campaign = _fake_db(campaign_timezone="Asia/Kolkata")
    execution = _execution(
        workflow.id,
        {
            "id": str(uuid.uuid4()),
            "name": "Ada Lovelace",
            "phone": "+14155550199",
            "email": "ada@example.com",
            "timezone": "America/New_York",
        },
    )

    dial = _campaign_dial_context(db, execution)

    assert dial is not None
    assert dial["timezone"] == "America/New_York"


def test_campaign_dial_payload_passes_timezone_to_call_extra_context():
    db, workflow, _campaign = _fake_db(campaign_timezone="Asia/Kolkata")
    execution = _execution(
        workflow.id,
        {
            "id": str(uuid.uuid4()),
            "name": "Ada Lovelace",
            "phone": "+14155550199",
            "email": "ada@example.com",
        },
    )
    dial = _campaign_dial_context(db, execution)
    assert dial is not None

    payload = _build_dial_payload(dial, execution)

    assert payload["extra_context"] == {
        "lead_email": "ada@example.com",
        "timezone": "Asia/Kolkata",
    }
