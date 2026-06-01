"""Campaign integration tests — cover §4.2, §4.3."""

from __future__ import annotations

import uuid

import pytest


def _create_campaign(client, headers):
    r = client.post(
        "/api/v1/campaigns",
        json={"name": f"E2E Campaign {uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_campaign_routes_require_auth(client):
    """Bug 4.3 — /campaigns/execute and /campaigns/executions used to be public."""

    fake_id = "00000000-0000-0000-0000-000000000001"

    r1 = client.post(f"/api/v1/campaigns/execute/{fake_id}")
    assert r1.status_code in (401, 403)

    r2 = client.get(f"/api/v1/campaigns/executions/{fake_id}")
    assert r2.status_code in (401, 403)


def test_campaign_create_activate_flow(client, auth_headers):
    camp = _create_campaign(client, auth_headers)
    assert camp["status"] == "draft"

    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": camp["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "active"
    assert "workflow_id" in body


def test_campaign_activate_404_on_unknown_id(client, auth_headers):
    """Bug fix — used to be 500 on missing campaign."""

    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": "00000000-0000-0000-0000-000000000001"},
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_executions_404_when_unknown(client, auth_headers):
    """Bug fix — used to AttributeError -> 500 on missing execution."""

    r = client.get(
        "/api/v1/campaigns/executions/00000000-0000-0000-0000-000000000001",
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_cross_org_workflow_execute_returns_404(client, auth_headers, second_user):
    """Bug 4.3 + tenant safety — other org's workflow must be invisible."""

    camp = _create_campaign(client, auth_headers)
    activate = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": camp["id"]},
        headers=auth_headers,
    ).json()
    wf_id = activate["workflow_id"]

    # Second tenant tries to execute tenant 1's workflow.
    r = client.post(
        f"/api/v1/campaigns/execute/{wf_id}",
        headers=second_user["headers"],
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_campaign_execute_does_not_500(client, auth_headers, monkeypatch):
    """Bug 4.2 — worker.run_execution used to call AIService.execute() which
    no longer exists; every execute returned 500. We stub the LLM call so the
    test doesn't depend on OpenAI but still exercises the real code path
    end-to-end.
    """

    from dataclasses import dataclass

    from modules.ai import schema as ai_schema
    from modules.campaign import worker as campaign_worker

    @dataclass
    class _FakeStats:
        total_tokens: int = 7
        model: str = "fake"

    @dataclass
    class _FakeResult:
        text: str = "queued"
        stats: _FakeStats = None

    class _FakeClient:
        async def complete(self, *_args, **_kwargs):
            return _FakeResult(text="ok", stats=_FakeStats())

    monkeypatch.setattr(
        campaign_worker, "get_openai", lambda: _FakeClient()
    )

    # Lightweight ChatMessage round-trip sanity check.
    msg = ai_schema.ChatMessage(role=ai_schema.MessageRole.USER, content="hi")
    assert msg.content == "hi"

    camp = _create_campaign(client, auth_headers)
    activate = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": camp["id"]},
        headers=auth_headers,
    ).json()

    r = client.post(
        f"/api/v1/campaigns/execute/{activate['workflow_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("completed", "failed")
    # Status row reachable now that auth is enforced.
    status = client.get(
        f"/api/v1/campaigns/executions/{body['execution_id']}",
        headers=auth_headers,
    )
    assert status.status_code == 200
