"""Sustained-load tests against Redis (async)."""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest
import redis
import redis.asyncio as aioredis

from config.settings import settings
from tests._support.benchmark import get_recorder


def _redis_available() -> bool:
    try:
        return bool(redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.performance,
    pytest.mark.integration,
    pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable"),
]


CONCURRENCY = int(os.environ.get("PERF_REDIS_CONCURRENCY", "16"))
REQUESTS = int(os.environ.get("PERF_REDIS_REQUESTS", "300"))


async def test_redis_sustained_set_get():
    rec = get_recorder()
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(idx: int) -> None:
        async with sem:
            key = f"perf:{idx}:{uuid.uuid4().hex[:6]}"
            t0 = time.perf_counter()
            try:
                await r.set(key, "v", ex=30)
                await r.get(key)
                await r.delete(key)
                ok = True
            except Exception:
                ok = False
            rec.record(
                category="perf",
                name="redis SET+GET+DEL",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                success=ok,
                metadata={
                    "concurrency": CONCURRENCY,
                    "requests": REQUESTS,
                },
            )

    try:
        await asyncio.gather(*(one(i) for i in range(REQUESTS)))
    finally:
        await r.aclose()
