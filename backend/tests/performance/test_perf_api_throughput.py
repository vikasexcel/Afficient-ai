"""Burst-throughput tests for the HTTP API.

Drives N concurrent requests against the FastAPI app via a thread pool
(``TestClient`` is sync) and records the per-request latency in the
``perf`` category.
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import time

import pytest

from tests._support.benchmark import get_recorder


pytestmark = [pytest.mark.performance, pytest.mark.api]


CONCURRENCY = int(os.environ.get("PERF_API_CONCURRENCY", "8"))
REQUESTS = int(os.environ.get("PERF_API_REQUESTS", "80"))


def _hit(client, url: str, *, headers: dict | None = None) -> tuple[int, float]:
    started = time.perf_counter()
    r = client.get(url, headers=headers or {})
    return r.status_code, (time.perf_counter() - started) * 1000.0


def _drive(client, url: str, *, headers: dict | None = None) -> None:
    rec = get_recorder()
    pool = cf.ThreadPoolExecutor(max_workers=CONCURRENCY)
    try:
        futures = [
            pool.submit(_hit, client, url, headers=headers) for _ in range(REQUESTS)
        ]
        for f in cf.as_completed(futures):
            status, latency_ms = f.result()
            rec.record(
                category="perf",
                name=f"throughput {url}",
                latency_ms=latency_ms,
                success=200 <= status < 400,
                metadata={
                    "concurrency": CONCURRENCY,
                    "requests": REQUESTS,
                    "status": status,
                },
            )
    finally:
        pool.shutdown(wait=True)


def test_throughput_health_endpoint(client):
    _drive(client, "/api/v1/health")


def test_throughput_root_endpoint(client):
    _drive(client, "/")


def test_throughput_personas_endpoint(client, auth_headers):
    _drive(client, "/api/v1/ai/personas", headers=auth_headers)


def test_throughput_leads_listing(client, auth_headers):
    _drive(client, "/api/v1/leads", headers=auth_headers)


def test_perf_recorder_has_samples(recorder):
    samples = [s for s in recorder.samples if s.category == "perf"]
    assert samples, "expected throughput samples"
