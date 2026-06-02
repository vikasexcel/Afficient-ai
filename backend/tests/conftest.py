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

Latency / performance benchmarks register samples into the
:class:`tests._support.benchmark.BenchmarkRecorder`; ``pytest_sessionfinish``
writes ``tests/reports/latency_report.json`` + ``performance_report.html``
whenever the recorder is non-empty.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Iterator

import pytest


# Disable the rate limiter so the integration tests don't trip the
# per-IP budget shared with the rest of the running app. Must be set
# *before* importing the app so the setting is read at import time.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


# Make ``tests/_support`` importable regardless of where pytest is invoked
# from (``pytest tests/unit`` vs. ``pytest tests``).
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))


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


@pytest.fixture(autouse=True)
def _reset_async_rate_limit_client():
    """``common.security.rate_limit`` caches an ``aioredis`` client globally.

    pytest-asyncio spins up a fresh event loop per test, so the cached
    client (bound to a previous loop) raises
    ``RuntimeError: Event loop is closed`` on the next async test that
    touches it. Reset the singleton around every test to keep the suite
    independent of execution order.
    """

    try:
        from common.security import rate_limit

        rate_limit._async_client = None
    except Exception:
        pass
    yield
    try:
        from common.security import rate_limit

        rate_limit._async_client = None
    except Exception:
        pass


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


# ---------------------------------------------------------------------------
# Benchmark recorder + reporter session hooks
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def recorder():
    """Process-wide latency/perf benchmark recorder."""

    from tests._support.benchmark import get_recorder

    return get_recorder()


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover - hook
    """Persist benchmark samples to ``tests/reports/`` when any were recorded."""

    from tests._support.benchmark import get_recorder
    from tests._support.reporter import (
        build_payload,
        format_console_summary,
        write_reports,
    )

    rec = get_recorder()
    if not rec.samples:
        return

    out = write_reports(rec)
    payload = build_payload(rec)
    summary = format_console_summary(payload)
    try:
        session.config._get_terminal_writer().line(summary)
    except Exception:
        print(summary)
    if out is not None:
        print(
            f"\nReports written to:\n  - {out[0]}\n  - {out[1]}\n"
        )
