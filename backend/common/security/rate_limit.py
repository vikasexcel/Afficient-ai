"""Redis-backed fixed-window rate limiter.

Two surfaces:

* :func:`limit_async` — call from async middleware; uses ``redis.asyncio``
  so the event loop is not blocked.
* :func:`limit` — sync helper preserved for legacy callers (e.g. unit
  tests). Avoid in hot paths.

The limit key shape is ``rl:<bucket>:<identity>``; the limiter scopes by
authenticated user where possible and falls back to the client IP.

Atomicity
---------
Both implementations use a single Lua script to atomically increment the
counter AND set its expiry in one round-trip.  The previous INCR + EXPIRE
pattern had a TOCTOU gap: if the process restarted between the two commands
the key would never expire and the bucket would be permanently blocked.

The Lua script:
  1. INCR key
  2. If new count == 1 (first hit in this window): SET EXPIRE
  3. Return the new count

Because Redis executes Lua scripts atomically (single-threaded eval) the
count + expire pair is always consistent.
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

# Atomic increment-with-expiry Lua script.
# KEYS[1] = rate-limit bucket key
# ARGV[1] = window length in seconds
# Returns: new count after increment
_LUA_INCR_EXPIRE = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


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
        max_requests if max_requests is not None else settings.RATE_LIMIT_REQUESTS
    )
    window = window if window is not None else settings.RATE_LIMIT_WINDOW_SECONDS

    count = _sync().eval(_LUA_INCR_EXPIRE, 1, key, window)  # type: ignore[arg-type]
    if count > max_requests:
        raise HTTPException(429, "Too many requests")


async def limit_async(
    key: str,
    max_requests: int | None = None,
    window: int | None = None,
) -> None:
    """Non-blocking fixed-window limiter, used by ``RateLimitMiddleware``.

    Uses an atomic Lua script (INCR + conditional EXPIRE in one eval) so
    the counter and its TTL are always consistent even under concurrent
    requests or server restarts.
    """

    max_requests = (
        max_requests if max_requests is not None else settings.RATE_LIMIT_REQUESTS
    )
    window = window if window is not None else settings.RATE_LIMIT_WINDOW_SECONDS

    client = _async()
    count = await client.eval(_LUA_INCR_EXPIRE, 1, key, window)  # type: ignore[arg-type]
    if count > max_requests:
        raise HTTPException(429, "Too many requests")


async def reset_async(key: str) -> None:
    """Drop a rate-limit bucket (used in tests)."""

    await _async().delete(key)
