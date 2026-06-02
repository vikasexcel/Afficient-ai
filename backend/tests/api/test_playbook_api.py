"""HTTP coverage for /api/v1/playbooks (CRUD, publish, archive, test)."""

from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.api


def _payload(name: str | None = None) -> dict:
    return {
        "name": name or f"PB {uuid.uuid4().hex[:6]}",
        "framework": "BANT",
        "persona_name": "outbound_sdr",
        "opening_line": "Hi, this is Aifficient.",
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


def test_list_playbooks_seeds_defaults_for_new_org(client, auth_headers):
    r = client.get("/api/v1/playbooks", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    names = {p["name"] for p in body["playbooks"]}
    # Defaults at minimum contain a BANT template.
    assert any("BANT" in n or "bant" in n.lower() for n in names)


def test_create_get_update_publish_archive_cycle(client, auth_headers):
    create = client.post(
        "/api/v1/playbooks", json=_payload(), headers=auth_headers
    )
    assert create.status_code == 201, create.text
    pb_id = create.json()["id"]

    fetched = client.get(f"/api/v1/playbooks/{pb_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == pb_id

    updated = client.patch(
        f"/api/v1/playbooks/{pb_id}",
        json={"description": "tweaked"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "tweaked"

    published = client.post(
        f"/api/v1/playbooks/{pb_id}/publish", json={}, headers=auth_headers
    )
    assert published.status_code == 200
    assert published.json()["status"] == "active"

    archived = client.post(
        f"/api/v1/playbooks/{pb_id}/archive", json={}, headers=auth_headers
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_publish_creates_a_version(client, auth_headers):
    r = client.post("/api/v1/playbooks", json=_payload(), headers=auth_headers)
    pb_id = r.json()["id"]
    client.post(f"/api/v1/playbooks/{pb_id}/publish", json={}, headers=auth_headers)
    versions = client.get(
        f"/api/v1/playbooks/{pb_id}/versions", headers=auth_headers
    )
    assert versions.status_code == 200
    body = versions.json()
    assert body["versions"], body
    assert body["versions"][0]["version"] >= 1


def test_test_endpoint_returns_branches_for_strong_input(client, auth_headers):
    r = client.post("/api/v1/playbooks", json=_payload(), headers=auth_headers)
    pb_id = r.json()["id"]
    client.post(f"/api/v1/playbooks/{pb_id}/publish", json={}, headers=auth_headers)

    test = client.post(
        f"/api/v1/playbooks/{pb_id}/test",
        json={"user_text": "budget is $50,000 this quarter"},
        headers=auth_headers,
    )
    assert test.status_code == 200, test.text
    body = test.json()
    assert "rendered_system_prompt" in body
    assert "branches_fired" in body


def test_preview_endpoint_returns_system_prompt(client, auth_headers):
    r = client.post("/api/v1/playbooks", json=_payload(), headers=auth_headers)
    pb_id = r.json()["id"]
    preview = client.get(
        f"/api/v1/playbooks/{pb_id}/preview", headers=auth_headers
    )
    assert preview.status_code == 200
    body = preview.json()
    assert "rendered_system_prompt" in body
    assert len(body["rendered_system_prompt"]) > 50


def test_duplicate_endpoint_creates_new_draft(client, auth_headers):
    r = client.post("/api/v1/playbooks", json=_payload(), headers=auth_headers)
    pb_id = r.json()["id"]
    dup = client.post(
        f"/api/v1/playbooks/{pb_id}/duplicate", json={}, headers=auth_headers
    )
    assert dup.status_code == 200
    body = dup.json()
    assert body["id"] != pb_id
    assert body["status"] == "draft"
