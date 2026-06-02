"""HTTP coverage for /api/v1/leads + /api/v1/lead-lists."""

from __future__ import annotations

import io
import uuid

import pytest


pytestmark = pytest.mark.api


_CSV_HEADER = "name,email,phone,company,industry,location,tags\n"


def _csv(rows: list[str]) -> bytes:
    return (_CSV_HEADER + "\n".join(rows) + "\n").encode("utf-8")


def test_list_lead_lists_is_empty_for_new_org(client, auth_headers):
    r = client.get("/api/v1/lead-lists", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["lead_lists"] == []


def test_create_lead_list_returns_201(client, auth_headers):
    r = client.post(
        "/api/v1/lead-lists",
        json={"name": f"Pytest List {uuid.uuid4().hex[:6]}"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"].startswith("Pytest List ")
    assert body["lead_count"] == 0


def test_duplicate_lead_list_name_returns_409(client, auth_headers):
    name = f"Pytest List {uuid.uuid4().hex[:6]}"
    client.post("/api/v1/lead-lists", json={"name": name}, headers=auth_headers)
    again = client.post(
        "/api/v1/lead-lists", json={"name": name}, headers=auth_headers
    )
    assert again.status_code == 409


def test_upload_preview_parses_csv_and_classifies_rows(client, auth_headers):
    payload = _csv(
        [
            "Jane,jane@example.com,+14155551212,Acme,Tech,SF,",
            "Bad,not-an-email,+14155551313,Acme,,,",
            "Dup1,d@example.com,+14155551414,,,,",
            "Dup2,d2@example.com,+1 (415) 555-1414,,,,",
            ",,,,,,",  # blank — should be skipped
        ]
    )
    r = client.post(
        "/api/v1/leads/upload/preview",
        headers={**auth_headers},
        files={"file": ("leads.csv", payload, "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    statuses = [r["status"] for r in body["rows"]]
    assert "valid" in statuses
    assert "invalid" in statuses
    assert "duplicate" in statuses
    assert body["detected_columns"]["name"] == "name"
    assert body["stats"]["valid"] >= 1


def test_upload_commit_inserts_valid_rows(client, auth_headers):
    list_name = f"Upload {uuid.uuid4().hex[:6]}"
    commit = client.post(
        "/api/v1/leads/upload/commit",
        json={
            "rows": [
                {
                    "name": "Jane Doe",
                    "email": "jane@example.com",
                    "phone": "+14155551212",
                    "company": "Acme",
                }
            ],
            "segmentation": {"tags": ["pytest"]},
            "new_list_name": list_name,
        },
        headers=auth_headers,
    )
    assert commit.status_code == 200, commit.text
    body = commit.json()
    assert body["inserted"] == 1
    assert body["lead_list"]["name"] == list_name

    leads = client.get(
        f"/api/v1/leads?lead_list_id={body['lead_list']['id']}",
        headers=auth_headers,
    )
    assert leads.status_code == 200
    assert leads.json()["total"] == 1


def test_upload_preview_rejects_non_csv(client, auth_headers):
    r = client.post(
        "/api/v1/leads/upload/preview",
        headers={**auth_headers},
        files={"file": ("leads.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_unauth_endpoints_reject_anonymous(client):
    assert client.get("/api/v1/lead-lists").status_code in (401, 403)
    assert client.get("/api/v1/leads").status_code in (401, 403)
