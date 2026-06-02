"""Sustained-load test for JWT signing + decoding."""

from __future__ import annotations

import concurrent.futures as cf
import os
import time
import uuid

import pytest

from common.security.jwt import create_token, decode_token
from tests._support.benchmark import get_recorder


pytestmark = pytest.mark.performance


CONCURRENCY = int(os.environ.get("PERF_JWT_CONCURRENCY", "16"))
ITERATIONS = int(os.environ.get("PERF_JWT_REQUESTS", "400"))


def _worker() -> tuple[bool, float]:
    started = time.perf_counter()
    try:
        token = create_token(str(uuid.uuid4()))
        payload = decode_token(token)
        ok = payload is not None
    except Exception:
        ok = False
    return ok, (time.perf_counter() - started) * 1000.0


def test_jwt_create_decode_concurrent():
    rec = get_recorder()
    pool = cf.ThreadPoolExecutor(max_workers=CONCURRENCY)
    try:
        futures = [pool.submit(_worker) for _ in range(ITERATIONS)]
        for f in cf.as_completed(futures):
            ok, lat = f.result()
            rec.record(
                category="perf",
                name="jwt create+decode (concurrent)",
                latency_ms=lat,
                success=ok,
                metadata={
                    "concurrency": CONCURRENCY,
                    "requests": ITERATIONS,
                },
            )
    finally:
        pool.shutdown(wait=True)
