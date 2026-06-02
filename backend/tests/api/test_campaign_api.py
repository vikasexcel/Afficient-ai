"""HTTP coverage for /api/v1/campaigns (positive flow)."""

from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.api


def test_campaign_create_returns_draft(client, auth_headers):
    r = client.post(
        "/api/v1/campaigns",
        json={"name": f"API Campaign {uuid.uuid4().hex[:6]}"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert uuid.UUID(body["id"])  # valid uuid


def test_campaign_full_activate_returns_workflow_id(client, auth_headers):
    create = client.post(
        "/api/v1/campaigns",
        json={"name": f"API Campaign {uuid.uuid4().hex[:6]}"},
        headers=auth_headers,
    )
    cid = create.json()["id"]
    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "active"
    assert uuid.UUID(body["workflow_id"])


def test_anonymous_caller_is_rejected(client):
    r = client.post("/api/v1/campaigns", json={"name": "x"})
    assert r.status_code in (401, 403)
