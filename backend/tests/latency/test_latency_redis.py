"""Latency benchmarks for Redis operations used by AI memory + rate limiter."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import redis
import redis.asyncio as aioredis

from common.security import rate_limit
from config.settings import settings
from modules.ai.memory import ConversationMemory
from modules.ai.schema import ChatMessage, MessageRole
from tests._support.benchmark import measure, measure_async


def _redis_available() -> bool:
    try:
        return bool(redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.latency,
    pytest.mark.integration,
    pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable"),
]


ITERATIONS = int(os.environ.get("BENCH_REDIS_ITERATIONS", "50"))


def test_latency_redis_sync_ping():
    r = redis.from_url(settings.REDIS_URL)
    for _ in range(ITERATIONS):
        with measure("redis", "sync PING"):
            r.ping()


async def test_latency_redis_async_ping():
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        for _ in range(ITERATIONS):
            async with measure_async("redis", "async PING"):
                await r.ping()
    finally:
        await r.aclose()


async def test_latency_redis_set_get_round_trip():
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    key = f"bench:{uuid.uuid4().hex[:10]}"
    try:
        for _ in range(ITERATIONS):
            async with measure_async("redis", "SET key=str"):
                await r.set(key, "value", ex=60)
            async with measure_async("redis", "GET key"):
                assert await r.get(key) == "value"
    finally:
        await r.delete(key)
        await r.aclose()


async def test_latency_ai_memory_append_history():
    memory = ConversationMemory()
    call_id = f"bench-{uuid.uuid4().hex[:10]}"
    try:
        for _ in range(ITERATIONS):
            async with measure_async("redis", "ConversationMemory.append"):
                await memory.append_message(
                    call_id,
                    ChatMessage(role=MessageRole.USER, content="hello"),
                )
        async with measure_async("redis", "ConversationMemory.snapshot"):
            await memory.snapshot(call_id)
    finally:
        await memory.clear_history(call_id)


async def test_latency_rate_limit_async_check():
    key = f"rl:bench:{uuid.uuid4().hex[:10]}"
    try:
        for _ in range(ITERATIONS):
            async with measure_async("redis", "rate_limit.limit_async"):
                await rate_limit.limit_async(key, max_requests=10**6, window=60)
    finally:
        await rate_limit.reset_async(key)
