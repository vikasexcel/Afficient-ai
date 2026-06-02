"""Latency benchmarks for the HTTP API surface.

These tests hit live endpoints through the FastAPI TestClient. Each
endpoint is sampled ``ITERATIONS`` times and the per-call latency is
recorded into the global :class:`BenchmarkRecorder` so the session-end
hook can summarise it.
"""

from __future__ import annotations

import os
import uuid

import pytest

from tests._support.benchmark import get_recorder, measure


pytestmark = [pytest.mark.latency, pytest.mark.api]


# Keep counts small enough to finish in a few seconds on a workstation
# but large enough that p95/p99 numbers are meaningful.
ITERATIONS = int(os.environ.get("BENCH_API_ITERATIONS", "30"))


def test_latency_root_endpoint(client):
    for _ in range(ITERATIONS):
        with measure("api", "GET /", metadata={"endpoint": "/"}):
            r = client.get("/")
            assert r.status_code == 200


def test_latency_health_endpoint(client):
    for _ in range(ITERATIONS):
        with measure("api", "GET /api/v1/health"):
            r = client.get("/api/v1/health")
            assert r.status_code == 200


def test_latency_auth_me_endpoint(client, auth_headers):
    for _ in range(ITERATIONS):
        with measure("api", "GET /api/v1/auth/me"):
            r = client.get("/api/v1/auth/me", headers=auth_headers)
            assert r.status_code == 200


def test_latency_auth_tenant_endpoint(client, auth_headers):
    for _ in range(ITERATIONS):
        with measure("api", "GET /api/v1/auth/tenant"):
            r = client.get("/api/v1/auth/tenant", headers=auth_headers)
            assert r.status_code == 200


def test_latency_auth_audit_endpoint(client, auth_headers):
    for _ in range(ITERATIONS):
        with measure("api", "GET /api/v1/auth/audit"):
            r = client.get(
                "/api/v1/auth/audit?limit=10", headers=auth_headers
            )
            assert r.status_code == 200


def test_latency_personas_endpoint(client, auth_headers):
    for _ in range(ITERATIONS):
        with measure("api", "GET /api/v1/ai/personas"):
            r = client.get("/api/v1/ai/personas", headers=auth_headers)
            assert r.status_code == 200


def test_latency_playbooks_listing(client, auth_headers):
    for _ in range(ITERATIONS):
        with measure("api", "GET /api/v1/playbooks"):
            r = client.get("/api/v1/playbooks", headers=auth_headers)
            assert r.status_code == 200


def test_latency_leads_listing(client, auth_headers):
    for _ in range(ITERATIONS):
        with measure("api", "GET /api/v1/leads"):
            r = client.get("/api/v1/leads", headers=auth_headers)
            assert r.status_code == 200


def test_latency_telephony_calls_listing(client, auth_headers):
    for _ in range(ITERATIONS):
        with measure("api", "GET /api/v1/telephony/calls"):
            r = client.get("/api/v1/telephony/calls", headers=auth_headers)
            assert r.status_code == 200


def test_latency_summary_has_samples(recorder):
    """Sanity check: the recorder picked up the previous benchmarks."""

    api_samples = [s for s in recorder.samples if s.category == "api"]
    assert api_samples, "expected at least one API latency sample"
