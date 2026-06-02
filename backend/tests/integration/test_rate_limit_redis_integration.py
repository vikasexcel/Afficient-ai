"""Integration tests for the Redis-backed rate limiter.

These mirror the existing behaviour exercised by ``test_security_and_misc``
but lean on the async path more aggressively (concurrent callers, key
expiry, mixed bucket sizes).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import redis
from fastapi import HTTPException

from common.security import rate_limit
from config.settings import settings


def _redis_available() -> bool:
    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        return bool(r.ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable"),
]


@pytest.fixture
def key() -> str:
    return f"rl:test:{uuid.uuid4().hex[:10]}"


async def test_limit_async_allows_up_to_max_requests(key: str):
    try:
        for _ in range(5):
            await rate_limit.limit_async(key, max_requests=5, window=5)
    finally:
        await rate_limit.reset_async(key)


async def test_limit_async_raises_429_once_exceeded(key: str):
    try:
        for _ in range(5):
            await rate_limit.limit_async(key, max_requests=5, window=5)
        with pytest.raises(HTTPException) as excinfo:
            await rate_limit.limit_async(key, max_requests=5, window=5)
        assert excinfo.value.status_code == 429
    finally:
        await rate_limit.reset_async(key)


async def test_limit_async_concurrent_callers_share_one_bucket(key: str):
    """Burst test — N concurrent coroutines must drain the same bucket."""

    try:
        results: list[bool] = []

        async def hit() -> bool:
            try:
                await rate_limit.limit_async(key, max_requests=10, window=5)
                return True
            except HTTPException:
                return False

        results = await asyncio.gather(*[hit() for _ in range(20)])
        # 10 should succeed, 10 should fail.
        assert sum(results) == 10
    finally:
        await rate_limit.reset_async(key)


async def test_reset_clears_the_bucket(key: str):
    for _ in range(3):
        await rate_limit.limit_async(key, max_requests=3, window=5)
    await rate_limit.reset_async(key)
    # Should accept again after reset.
    await rate_limit.limit_async(key, max_requests=3, window=5)
    await rate_limit.reset_async(key)
