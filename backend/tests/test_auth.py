"""Auth integration tests — cover every fix in §4.4–4.6, §4.1."""

from __future__ import annotations

import uuid


def test_register_returns_200_with_ids(client):
    suffix = uuid.uuid4().hex[:8]
    r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Reg Test",
            "email": f"reg+{suffix}@example.com",
            "password": "Hunter12345!",
            "organization": f"Reg Org {suffix}",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"] == "registered"
    # Bonus: fix 4.5 should also return identifiers so the SPA can chain.
    assert "user_id" in body and "organization_id" in body


def test_register_duplicate_returns_409(client, unique_user):
    """Bug 4.5 — was 500; must now be 409."""

    r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Dup",
            "email": unique_user["email"],
            "password": "Hunter12345!",
            "organization": "Dup Org",
        },
    )
    assert r.status_code == 409, r.text
    assert "already" in r.json()["detail"].lower()


def test_register_rejects_short_password(client):
    """Bug 4.6 — empty / very short password used to be accepted (200)."""

    r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Weak",
            "email": f"weak+{uuid.uuid4().hex[:6]}@example.com",
            "password": "",
            "organization": "Weak Org",
        },
    )
    assert r.status_code == 422

    r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Weak",
            "email": f"weak2+{uuid.uuid4().hex[:6]}@example.com",
            "password": "a",
            "organization": "Weak Org",
        },
    )
    assert r.status_code == 422


def test_register_rejects_letters_only_password(client):
    """Bug 4.6 — password must have at least one non-letter."""

    r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Weak",
            "email": f"alpha+{uuid.uuid4().hex[:6]}@example.com",
            "password": "abcdefghij",  # 10 letters, no digit/symbol
            "organization": "Weak Org",
        },
    )
    assert r.status_code == 422


def test_register_rejects_password_longer_than_bcrypt_limit(client):
    """Bug 4.6 — bcrypt silently truncates >72 bytes. Reject explicitly."""

    r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Long",
            "email": f"long+{uuid.uuid4().hex[:6]}@example.com",
            "password": "a" * 73 + "1!",
            "organization": "Long Org",
        },
    )
    assert r.status_code == 422


def test_login_wrong_password_returns_401(client, unique_user):
    """Bug 4.4 — used to return 200 with {error:invalid}."""

    r = client.post(
        "/api/v1/auth/login",
        json={"email": unique_user["email"], "password": "wrongpass1!"},
    )
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()


def test_login_unknown_email_returns_401(client):
    """Bug 4.4 — same response for unknown emails to prevent enumeration."""

    r = client.post(
        "/api/v1/auth/login",
        json={
            "email": f"noone+{uuid.uuid4().hex[:8]}@example.com",
            "password": "Hunter12345!",
        },
    )
    assert r.status_code == 401


def test_refresh_invalid_token_returns_401(client):
    """Bug 4.4 — refresh used to return 200 with {error:...}."""

    r = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "definitely-not-a-real-token"},
    )
    assert r.status_code == 401


def test_logout_idempotent_for_unknown_token(client):
    """Bug 4.4 — graceful 200 ok rather than 200 with error or 5xx."""

    r = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "unknown.refresh.token"},
    )
    assert r.status_code == 200


def test_audit_requires_auth(client):
    """Bug 4.1 — /auth/audit used to return the entire DB unauthenticated."""

    r = client.get("/api/v1/auth/audit")
    assert r.status_code in (401, 403), r.text


def test_audit_is_scoped_to_org(client, unique_user, second_user):
    """Bug 4.1 — even authenticated callers must only see their org."""

    r1 = client.get(
        "/api/v1/auth/audit",
        headers={"Authorization": f"Bearer {unique_user['access_token']}"},
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert "entries" in body1 and "total" in body1
    user1_emails = {e["details"] for e in body1["entries"] if e["action"] == "REGISTER"}
    assert unique_user["email"] in user1_emails
    # Critically, the second tenant's email must not appear in tenant 1's view.
    second_email_seen = any(
        e.get("details", "").startswith("pytest2+") for e in body1["entries"]
    )
    assert not second_email_seen

    # And the second tenant must not see tenant 1's REGISTER row.
    r2 = client.get("/api/v1/auth/audit", headers=second_user["headers"])
    assert r2.status_code == 200
    body2 = r2.json()
    bleed = any(
        e.get("details") == unique_user["email"] for e in body2["entries"]
    )
    assert not bleed


def test_audit_pagination_caps_payload(client, unique_user):
    """Bug 4.13 — audit endpoint paginated."""

    r = client.get(
        "/api/v1/auth/audit?limit=2&offset=0",
        headers={"Authorization": f"Bearer {unique_user['access_token']}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["entries"]) <= 2
