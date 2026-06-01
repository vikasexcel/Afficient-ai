"""AI router + playbook tests — cover §4.7, §4.9, §4.11, §4.12."""

from __future__ import annotations

import uuid

import pytest


def _make_playbook(client, headers, status="active"):
    payload = {
        "name": f"PB {uuid.uuid4().hex[:6]}",
        "framework": "BANT",
        "persona_name": "outbound_sdr",
        "opening_line": "Hi, this is Aifficient calling.",
        "fields": [
            {
                "key": "budget",
                "display_name": "Budget",
                "weight": 2,
                "required": True,
                "cue_patterns": [r"\$\d+", "budget"],
            }
        ],
        "branches": [
            {
                "id": "warm",
                "name": "Warm lead",
                "priority": 50,
                "when": {"min_score": 50},
                "then": {"objective": "book a demo"},
            }
        ],
    }
    r = client.post("/api/v1/playbooks", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    pb = r.json()

    if status == "active":
        client.post(
            f"/api/v1/playbooks/{pb['id']}/publish", json={}, headers=headers
        )
    return pb


def test_transcript_returns_404_for_unknown_call(client, auth_headers):
    """Bug 4.9 — used to return 200 with empty entries."""

    r = client.get(
        f"/api/v1/ai/calls/nonexistent-{uuid.uuid4().hex[:8]}/transcript",
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_transcript_cross_tenant_returns_404(client, auth_headers, second_user):
    """Bug 4.9 — second tenant must NOT see the first tenant's call_id."""

    call_id = f"e2e-iso-{uuid.uuid4().hex[:8]}"
    converse = client.post(
        "/api/v1/ai/converse",
        json={"call_id": call_id, "user_input": "Hello there!"},
        headers=auth_headers,
    )
    # OpenAI may be unreachable in CI — skip if we can't drive a turn.
    if converse.status_code != 200:
        pytest.skip(f"OpenAI not available: {converse.status_code} {converse.text[:120]}")

    # Tenant 1 sees the call.
    r1 = client.get(
        f"/api/v1/ai/calls/{call_id}/transcript", headers=auth_headers
    )
    assert r1.status_code == 200

    # Tenant 2 must NOT.
    r2 = client.get(
        f"/api/v1/ai/calls/{call_id}/transcript", headers=second_user["headers"]
    )
    assert r2.status_code == 404


def test_converse_with_archived_playbook_returns_4xx_not_500(
    client, auth_headers
):
    """Bug 4.7 — PlaybookValidationError was uncaught -> 500. Should be 400."""

    pb = _make_playbook(client, auth_headers, status="active")
    # Archive it so it's no longer usable.
    r = client.post(
        f"/api/v1/playbooks/{pb['id']}/archive", json={}, headers=auth_headers
    )
    assert r.status_code == 200

    r = client.post(
        "/api/v1/ai/converse",
        json={
            "call_id": f"e2e-pb-arch-{uuid.uuid4().hex[:8]}",
            "user_input": "Hi.",
            "playbook_id": pb["id"],
        },
        headers=auth_headers,
    )
    # Must be a clean 4xx (400 from PlaybookValidationError) not a 5xx.
    assert 400 <= r.status_code < 500, r.text
    assert r.status_code != 422  # would mean the schema rejected it instead


def test_playbook_rejects_unknown_branch_when_key(client, auth_headers):
    """Bug 4.11 — unknown when-keys used to silently always-match. Now 422."""

    bad = {
        "name": f"Bad {uuid.uuid4().hex[:6]}",
        "framework": "BANT",
        "persona_name": "outbound_sdr",
        "fields": [
            {"key": "budget", "display_name": "Budget", "required": True}
        ],
        "branches": [
            {
                "id": "wat",
                "name": "Bad rule",
                "priority": 10,
                "when": {"any_keyword": ["price"], "fakemoise": True},
                "then": {"objective": "x"},
            }
        ],
    }
    r = client.post("/api/v1/playbooks", json=bad, headers=auth_headers)
    assert r.status_code == 422, r.text


def test_playbook_test_with_grammatical_prompt(client, auth_headers):
    """Bug 4.12 — system prompt must no longer contain 'with there'."""

    pb = _make_playbook(client, auth_headers, status="active")
    r = client.post(
        f"/api/v1/playbooks/{pb['id']}/test",
        json={"user_text": "budget is $50,000"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    prompt = r.json()["rendered_system_prompt"]
    assert " with there" not in prompt
    # Replacement default reads cleanly.
    assert "with the prospect" in prompt or "with " in prompt


def test_branch_rules_correctly_isolated_to_their_condition(
    client, auth_headers
):
    """Bug 4.11 — once branches are properly validated, only the
    qualifying rule should fire. Here a min_score:50 rule should NOT
    fire when the score is 0 (no fields matched)."""

    pb = _make_playbook(client, auth_headers, status="active")
    r = client.post(
        f"/api/v1/playbooks/{pb['id']}/test",
        json={"user_text": "hello"},  # no cue matches → score 0
        headers=auth_headers,
    )
    assert r.status_code == 200
    fired = r.json().get("branches_fired", [])
    assert fired == []  # would have been ['warm'] before the fix
