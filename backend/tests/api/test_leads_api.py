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


# ---------------------------------------------------------------------------
# Manual create / update / delete
# ---------------------------------------------------------------------------


def _make_phone() -> str:
    return "+1415" + uuid.uuid4().int.__str__()[:7]


def test_create_lead_returns_201_and_appears_in_list(client, auth_headers):
    phone = _make_phone()
    r = client.post(
        "/api/v1/leads",
        json={
            "name": "Nishant Kumar",
            "email": "nishant@example.com",
            "phone": phone,
            "company": "Acme",
            "industry": "Software",
            "tags": ["warm", "warm", "vip"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Nishant Kumar"
    assert body["industry"] == "Software"
    # Tags are de-duped + sorted.
    assert body["tags"] == ["vip", "warm"]

    listed = client.get("/api/v1/leads", headers=auth_headers).json()["leads"]
    assert any(l["id"] == body["id"] for l in listed)


def test_create_lead_rejects_bad_phone_and_email(client, auth_headers):
    short = client.post(
        "/api/v1/leads",
        json={"name": "X", "phone": "123"},
        headers=auth_headers,
    )
    assert short.status_code == 422, short.text

    bad_email = client.post(
        "/api/v1/leads",
        json={"name": "X", "phone": _make_phone(), "email": "not-an-email"},
        headers=auth_headers,
    )
    assert bad_email.status_code == 422, bad_email.text


def test_create_lead_duplicate_phone_returns_409(client, auth_headers):
    phone = _make_phone()
    first = client.post(
        "/api/v1/leads",
        json={"name": "First", "phone": phone},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    # Same digits, different formatting → still a duplicate.
    dup = client.post(
        "/api/v1/leads",
        json={"name": "Second", "phone": phone.replace("+1", "+1 ")},
        headers=auth_headers,
    )
    assert dup.status_code == 409, dup.text


def test_update_lead_patches_fields(client, auth_headers):
    created = client.post(
        "/api/v1/leads",
        json={"name": "Editable", "phone": _make_phone()},
        headers=auth_headers,
    ).json()

    patched = client.patch(
        f"/api/v1/leads/{created['id']}",
        json={
            "name": "Edited Name",
            "industry": "Fintech",
            "status": "qualified",
            "tags": ["hot"],
        },
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "Edited Name"
    assert body["industry"] == "Fintech"
    assert body["status"] == "qualified"
    assert body["tags"] == ["hot"]


def test_get_lead_by_id(client, auth_headers):
    created = client.post(
        "/api/v1/leads",
        json={"name": "Lookup", "phone": _make_phone()},
        headers=auth_headers,
    ).json()
    r = client.get(f"/api/v1/leads/{created['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["name"] == "Lookup"
    # Unknown id → 404.
    assert (
        client.get(
            f"/api/v1/leads/{uuid.uuid4()}", headers=auth_headers
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Backend search (case-insensitive, partial, across all fields)
# ---------------------------------------------------------------------------


def test_search_matches_partial_industry_company_and_tags(client, auth_headers):
    tag = f"vip{uuid.uuid4().hex[:6]}"
    client.post(
        "/api/v1/leads",
        json={
            "name": "Sofia Industry Lead",
            "phone": _make_phone(),
            "company": "Globex",
            "industry": "Software",
            "tags": [tag],
        },
        headers=auth_headers,
    )

    # "sof" should match industry "Software" (case-insensitive partial).
    res = client.get(
        "/api/v1/leads", params={"search": "sof"}, headers=auth_headers
    ).json()
    assert any(
        l["industry"] == "Software" for l in res["leads"]
    ), res

    # Company partial match.
    res = client.get(
        "/api/v1/leads", params={"search": "globe"}, headers=auth_headers
    ).json()
    assert any(l["company"] == "Globex" for l in res["leads"])

    # Tag match.
    res = client.get(
        "/api/v1/leads", params={"search": tag}, headers=auth_headers
    ).json()
    assert any(tag in (l["tags"] or []) for l in res["leads"])


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


def test_log_and_list_activities(client, auth_headers):
    lead = client.post(
        "/api/v1/leads",
        json={"name": "Activity Lead", "phone": _make_phone()},
        headers=auth_headers,
    ).json()

    for kind in ("call", "note"):
        a = client.post(
            f"/api/v1/leads/{lead['id']}/activities",
            json={"activity_type": kind, "notes": f"{kind} happened"},
            headers=auth_headers,
        )
        assert a.status_code == 201, a.text
        assert a.json()["activity_type"] == kind

    listed = client.get(
        f"/api/v1/leads/{lead['id']}/activities", headers=auth_headers
    )
    assert listed.status_code == 200
    activities = listed.json()["activities"]
    assert len(activities) == 2
    # Newest first.
    assert activities[0]["created_at"] >= activities[1]["created_at"]


def test_log_activity_rejects_unknown_type(client, auth_headers):
    lead = client.post(
        "/api/v1/leads",
        json={"name": "Bad Activity", "phone": _make_phone()},
        headers=auth_headers,
    ).json()
    r = client.post(
        f"/api/v1/leads/{lead['id']}/activities",
        json={"activity_type": "carrier-pigeon"},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


def test_activities_404_for_unknown_lead(client, auth_headers):
    r = client.get(
        f"/api/v1/leads/{uuid.uuid4()}/activities", headers=auth_headers
    )
    assert r.status_code == 404
