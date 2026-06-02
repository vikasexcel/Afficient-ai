"""HTTP tests for the health endpoint."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.api


def test_health_returns_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "service": "backend"}


def test_root_returns_service_metadata(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert "service" in body
    assert "environment" in body


def test_unknown_path_returns_404(client):
    assert client.get("/api/v1/nope/does-not-exist").status_code == 404
