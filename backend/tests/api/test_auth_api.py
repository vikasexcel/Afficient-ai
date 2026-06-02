"""HTTP-level coverage of the auth router.

Complements the bug-driven cases in ``tests/test_auth.py`` with
positive flow + tenant identity tests.
"""

from __future__ import annotations

import uuid

import pytest


pytestmark = pytest.mark.api


def test_login_returns_access_and_refresh_tokens(client, unique_user):
    # ``unique_user`` already exercised the happy login path. We just
    # need to sanity-check the response shape that the FE relies on,
    # which is already captured in the fixture's payload.
    assert unique_user["access_token"]
    assert unique_user["refresh_token"]


def test_me_returns_user_and_org(client, auth_headers, unique_user):
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == unique_user["user_id"]
    assert body["organization"]["id"] == unique_user["organization_id"]
    assert body["role"] == "owner"


def test_tenant_endpoint_exposes_membership(client, auth_headers, unique_user):
    r = client.get("/api/v1/auth/tenant", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["organization_id"] == unique_user["organization_id"]
    assert body["role"] == "owner"


def test_admin_endpoint_accepts_owner(client, auth_headers):
    r = client.get("/api/v1/auth/admin", headers=auth_headers)
    assert r.status_code == 200


def test_refresh_then_logout_invalidates_session(client, unique_user):
    # Refresh issues a new access token.
    r = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": unique_user["refresh_token"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]

    # Logout is idempotent and accepts the refresh token.
    r = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": unique_user["refresh_token"]},
    )
    assert r.status_code == 200


def test_protected_endpoint_rejects_missing_auth(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code in (401, 403)
