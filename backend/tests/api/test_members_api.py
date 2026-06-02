"""HTTP coverage for /api/v1/members."""

from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.api


def test_members_list_returns_owner(client, auth_headers, unique_user):
    r = client.get("/api/v1/members", headers=auth_headers)
    assert r.status_code == 200, r.text
    members = r.json()
    assert isinstance(members, list)
    emails = {m["email"] for m in members}
    assert unique_user["email"] in emails


def test_create_member_returns_member_payload(client, auth_headers):
    email = f"member+{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/api/v1/members",
        json={"full_name": "New Member", "email": email, "role": "agent"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["member"]["email"] == email
    assert body["member"]["role"] == "agent"
    # Service generates a temp password when the account is new.
    assert body.get("temp_password")


def test_update_role_promotes_member(client, auth_headers):
    email = f"member+{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/members",
        json={"full_name": "Promote Me", "email": email, "role": "member"},
        headers=auth_headers,
    ).json()
    mid = created["member"]["membership_id"]

    r = client.patch(
        f"/api/v1/members/{mid}/role",
        json={"role": "admin"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


def test_remove_member_reports_success(client, auth_headers):
    email = f"member+{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/members",
        json={"full_name": "Bye", "email": email, "role": "member"},
        headers=auth_headers,
    ).json()
    mid = created["member"]["membership_id"]
    r = client.delete(f"/api/v1/members/{mid}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True


def test_members_list_requires_auth(client):
    assert client.get("/api/v1/members").status_code in (401, 403)
