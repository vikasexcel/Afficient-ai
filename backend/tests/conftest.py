"""Shared pytest fixtures.

Two scopes are provided:

* ``client`` — a FastAPI ``TestClient`` bound to the live ``app`` so
  integration tests exercise the real routing, middleware (rate-limit
  bypassed via env), DB session, and dependencies.
* ``unique_user`` — registers a fresh user/org via the public API and
  returns ``(email, password, access_token, refresh_token, org_id)``.
  Every call mints a brand-new user, so tests stay isolated from one
  another without needing a transactional rollback.

Tests assume Postgres + Redis are already running locally on the ports
configured in ``backend/.env``.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest


# Disable the rate limiter so the integration tests don't trip the
# per-IP budget shared with the rest of the running app. Must be set
# *before* importing the app so the setting is read at import time.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


@pytest.fixture(scope="session")
def client() -> Iterator:
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def unique_user(client) -> dict:
    """Register + login a fresh user. Returns auth context for the test."""

    suffix = uuid.uuid4().hex[:10]
    email = f"pytest+{suffix}@example.com"
    password = "Test123!Strong"
    org = f"Pytest Org {suffix}"

    r = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Pytest User",
            "email": email,
            "password": password,
            "organization": org,
        },
    )
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    ).json()

    return {
        "email": email,
        "password": password,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "organization_id": me["organization"]["id"],
        "user_id": me["id"],
    }


@pytest.fixture
def auth_headers(unique_user):
    return {"Authorization": f"Bearer {unique_user['access_token']}"}


@pytest.fixture
def second_user(client) -> dict:
    """A second tenant — used for cross-org isolation tests."""

    suffix = uuid.uuid4().hex[:10]
    email = f"pytest2+{suffix}@example.com"
    password = "Test123!Strong"

    client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Pytest User 2",
            "email": email,
            "password": password,
            "organization": f"Pytest Other Org {suffix}",
        },
    )
    tokens = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    ).json()
    return {
        "access_token": tokens["access_token"],
        "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
    }
