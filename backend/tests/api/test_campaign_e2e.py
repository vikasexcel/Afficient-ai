"""End-to-end coverage for the full campaign management flow.

Create campaign (with playbook + lead list + schedule + business hours)
-> list -> get -> patch -> activate (enqueues one execution per lead)
-> execute (runs the worker against a queued lead) -> delete.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest


pytestmark = pytest.mark.api


def _seed_playbook(client, headers) -> str:
    # GET /playbooks seeds the org's default playbooks and returns them.
    r = client.get("/api/v1/playbooks", headers=headers)
    assert r.status_code == 200, r.text
    playbooks = r.json()["playbooks"]
    assert playbooks, "expected seeded default playbooks"
    return playbooks[0]["id"]


def _seed_lead_list(client, headers, n: int = 2) -> tuple[str, int]:
    list_name = f"E2E List {uuid.uuid4().hex[:6]}"
    rows = [
        {
            "name": f"Lead {i}",
            "email": f"lead{i}.{uuid.uuid4().hex[:5]}@example.com",
            "phone": f"+1415555{1000 + i:04d}",
            "company": "Acme",
        }
        for i in range(n)
    ]
    r = client.post(
        "/api/v1/leads/upload/commit",
        json={
            "rows": rows,
            "segmentation": {"tags": ["e2e"]},
            "new_list_name": list_name,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["lead_list"]["id"], body["inserted"]


def _full_config(playbook_id: str, lead_list_id: str, name: str) -> dict:
    return {
        "name": name,
        "playbook_id": playbook_id,
        "lead_list_id": lead_list_id,
        "schedule": {
            "start_immediately": True,
            "date": None,
            "time": None,
            "timezone": "Asia/Kolkata",
        },
        # All days + a wide window so activation always starts "now".
        "business_hours": {
            "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "start": "00:00",
            "end": "23:59",
            "skip_holidays": False,
        },
    }


def test_campaign_full_config_is_persisted_and_listed(client, auth_headers):
    playbook_id = _seed_playbook(client, auth_headers)
    lead_list_id, inserted = _seed_lead_list(client, auth_headers, n=2)
    assert inserted == 2

    name = f"E2E Campaign {uuid.uuid4().hex[:6]}"
    create = client.post(
        "/api/v1/campaigns",
        json=_full_config(playbook_id, lead_list_id, name),
        headers=auth_headers,
    )
    assert create.status_code == 200, create.text
    cid = create.json()["id"]
    assert create.json()["status"] == "draft"

    # GET single — fields persisted + enriched.
    one = client.get(f"/api/v1/campaigns/{cid}", headers=auth_headers)
    assert one.status_code == 200, one.text
    body = one.json()
    assert body["playbook_id"] == playbook_id
    assert body["lead_list_id"] == lead_list_id
    assert body["timezone"] == "Asia/Kolkata"
    assert body["business_hours"]["start"] == "00:00"
    assert body["playbook_name"]
    assert body["lead_list_name"]
    assert body["lead_count"] == 2

    # LIST contains it.
    listed = client.get("/api/v1/campaigns", headers=auth_headers)
    assert listed.status_code == 200
    ids = [c["id"] for c in listed.json()["campaigns"]]
    assert cid in ids


def test_campaign_patch_updates_fields(client, auth_headers):
    playbook_id = _seed_playbook(client, auth_headers)
    lead_list_id, _ = _seed_lead_list(client, auth_headers, n=1)
    create = client.post(
        "/api/v1/campaigns",
        json=_full_config(playbook_id, lead_list_id, "Before Edit"),
        headers=auth_headers,
    )
    cid = create.json()["id"]

    patched = client.patch(
        f"/api/v1/campaigns/{cid}",
        json={"name": "After Edit", "status": "paused"},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "After Edit"
    assert patched.json()["status"] == "paused"


def test_campaign_patch_rejects_bad_status(client, auth_headers):
    playbook_id = _seed_playbook(client, auth_headers)
    lead_list_id, _ = _seed_lead_list(client, auth_headers, n=1)
    cid = client.post(
        "/api/v1/campaigns",
        json=_full_config(playbook_id, lead_list_id, "Bad Status"),
        headers=auth_headers,
    ).json()["id"]

    r = client.patch(
        f"/api/v1/campaigns/{cid}",
        json={"status": "not-a-status"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_campaign_activate_enqueues_one_execution_per_lead(
    client, auth_headers
):
    playbook_id = _seed_playbook(client, auth_headers)
    lead_list_id, inserted = _seed_lead_list(client, auth_headers, n=3)

    cid = client.post(
        "/api/v1/campaigns",
        json=_full_config(playbook_id, lead_list_id, "Activate Me"),
        headers=auth_headers,
    ).json()["id"]

    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "active"
    assert body["enqueued_leads"] == inserted
    assert uuid.UUID(body["workflow_id"])

    # Campaign status flipped to active.
    one = client.get(f"/api/v1/campaigns/{cid}", headers=auth_headers)
    assert one.json()["status"] == "active"


def test_campaign_future_schedule_holds_as_scheduled(client, auth_headers):
    playbook_id = _seed_playbook(client, auth_headers)
    lead_list_id, _ = _seed_lead_list(client, auth_headers, n=1)

    cfg = _full_config(playbook_id, lead_list_id, "Future Campaign")
    cfg["schedule"] = {
        "start_immediately": False,
        "date": "2099-01-01",
        "time": "09:00",
        "timezone": "UTC",
    }
    cid = client.post(
        "/api/v1/campaigns", json=cfg, headers=auth_headers
    ).json()["id"]

    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "scheduled"
    assert body["scheduled"] is True
    assert body["workflow_id"] is None


@pytest.mark.asyncio
async def test_campaign_execute_processes_a_queued_lead(
    client, auth_headers, monkeypatch
):
    from modules.campaign import worker as campaign_worker

    @dataclass
    class _FakeStats:
        total_tokens: int = 5
        model: str = "fake"

    @dataclass
    class _FakeResult:
        text: str = "call plan"
        stats: _FakeStats = None

    class _FakeClient:
        async def complete(self, *_a, **_k):
            return _FakeResult(text="call plan", stats=_FakeStats())

    monkeypatch.setattr(
        campaign_worker, "get_openai", lambda: _FakeClient()
    )

    playbook_id = _seed_playbook(client, auth_headers)
    lead_list_id, _ = _seed_lead_list(client, auth_headers, n=2)
    cid = client.post(
        "/api/v1/campaigns",
        json=_full_config(playbook_id, lead_list_id, "Execute Me"),
        headers=auth_headers,
    ).json()["id"]

    activate = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    ).json()

    r = client.post(
        f"/api/v1/campaigns/execute/{activate['workflow_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    # Ran against an enqueued lead, not a generic execution.
    assert body["lead_id"] is not None


def test_campaign_delete_then_404(client, auth_headers):
    playbook_id = _seed_playbook(client, auth_headers)
    lead_list_id, _ = _seed_lead_list(client, auth_headers, n=1)
    cid = client.post(
        "/api/v1/campaigns",
        json=_full_config(playbook_id, lead_list_id, "Delete Me"),
        headers=auth_headers,
    ).json()["id"]

    d = client.delete(f"/api/v1/campaigns/{cid}", headers=auth_headers)
    assert d.status_code == 204, d.text

    gone = client.get(f"/api/v1/campaigns/{cid}", headers=auth_headers)
    assert gone.status_code == 404


def test_campaign_delete_after_activation_cascades(client, auth_headers):
    """Bug 1 — deleting an activated campaign used to 500 on a FK violation
    because its workflows + executions had no ON DELETE cascade."""

    playbook_id = _seed_playbook(client, auth_headers)
    lead_list_id, _ = _seed_lead_list(client, auth_headers, n=2)
    cid = client.post(
        "/api/v1/campaigns",
        json=_full_config(playbook_id, lead_list_id, "Delete After Activate"),
        headers=auth_headers,
    ).json()["id"]

    # Activate so the campaign gets a workflow + queued executions.
    activate = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    )
    assert activate.status_code == 200, activate.text
    assert activate.json()["enqueued_leads"] == 2

    # Delete must now succeed and remove the campaign.
    d = client.delete(f"/api/v1/campaigns/{cid}", headers=auth_headers)
    assert d.status_code == 204, d.text

    gone = client.get(f"/api/v1/campaigns/{cid}", headers=auth_headers)
    assert gone.status_code == 404
