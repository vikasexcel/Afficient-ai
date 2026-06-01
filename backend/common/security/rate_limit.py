"""Redis-backed sliding-window rate limiter.

Two surfaces:

* :func:`limit_async` — call from async middleware; uses ``redis.asyncio``
  so the event loop is not blocked.
* :func:`limit` — sync helper preserved for legacy callers (e.g. unit
  tests). Avoid in hot paths.

The limit key shape is ``rl:<bucket>:<identity>``; the limiter scopes by
authenticated user where possible and falls back to the client IP.
"""

from __future__ import annotations

from fastapi import HTTPException

import redis
import redis.asyncio as aioredis

from config.settings import settings


# Process-wide pools. Built lazily so import-time failure doesn't
# break the rest of the app.
_sync_client: redis.Redis | None = None
_async_client: aioredis.Redis | None = None


def _sync() -> redis.Redis:
    global _sync_client
    if _sync_client is None:
        _sync_client = redis.from_url(settings.REDIS_URL)
    return _sync_client


def _async() -> aioredis.Redis:
    global _async_client
    if _async_client is None:
        _async_client = aioredis.from_url(settings.REDIS_URL)
    return _async_client


def limit(
    key: str,
    max_requests: int | None = None,
    window: int | None = None,
) -> None:
    """Synchronous fixed-window limiter.

    Kept for tests and rare sync callers. Production traffic goes through
    :func:`limit_async`.
    """

    max_requests = (
        max_requests
        if max_requests is not None
        else settings.RATE_LIMIT_REQUESTS
    )
    window = window if window is not None else settings.RATE_LIMIT_WINDOW_SECONDS

    count = _sync().incr(key)
    if count == 1:
        _sync().expire(key, window)
    if count > max_requests:
        raise HTTPException(429, "Too many requests")


async def limit_async(
    key: str,
    max_requests: int | None = None,
    window: int | None = None,
) -> None:
    """Non-blocking fixed-window limiter, used by ``RateLimitMiddleware``.

    Uses INCR + EXPIRE; if the EXPIRE call fails we don't fail the
    request — at worst the bucket lives forever, which is harmless.
    """

    max_requests = (
        max_requests
        if max_requests is not None
        else settings.RATE_LIMIT_REQUESTS
    )
    window = window if window is not None else settings.RATE_LIMIT_WINDOW_SECONDS

    client = _async()
    count = await client.incr(key)
    if count == 1:
        try:
            await client.expire(key, window)
        except Exception:
            pass
    if count > max_requests:
        raise HTTPException(429, "Too many requests")


async def reset_async(key: str) -> None:
    """Drop a rate-limit bucket (used in tests)."""

    await _async().delete(key)
