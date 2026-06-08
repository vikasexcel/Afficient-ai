"""Rate-limit middleware.

Wraps every request in a Redis-backed sliding window keyed by:

* the authenticated user id (preferred — extracted from the JWT in the
  ``Authorization: Bearer`` header) so legitimate users behind a shared
  NAT don't fight each other for budget, or
* the client IP as fallback.

Some endpoints are exempted: health probes, webhooks, docs, and CORS
preflight (``OPTIONS``). The login/register/refresh endpoints have a
much stricter dedicated budget so the limiter doubles as brute-force
protection.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from common.logging import get_logger
from common.security.jwt import decode_token
from common.security.rate_limit import limit_async
from config.settings import settings

log = get_logger("security.rate_limit")


def _exempt_prefixes() -> tuple[str, ...]:
    raw = settings.RATE_LIMIT_EXEMPT_PATHS or ""
    return tuple(
        p.strip() for p in raw.split(",") if p.strip()
    )


_AUTH_PATHS = (
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
)

# Expensive AI inference endpoints — dedicated lower budget to prevent
# cost amplification.  Matched on exact path + POST method.
_AI_INFERENCE_PATHS = (
    "/api/v1/ai/generate",
    "/api/v1/ai/converse",
)

# Real telephony origination — real Twilio cost + call volume impact.
_TELEPHONY_ORIGINATE_PATH = "/api/v1/telephony/calls"

# Campaign activation — triggers lead enqueueing, can be slow.
_CAMPAIGN_ACTIVATE_PATH = "/api/v1/campaigns/activate"


def _is_exempt(path: str) -> bool:
    """Cheap prefix scan against the configured exemption list.

    Rules:
    * ``/`` is treated as an EXACT match (otherwise everything starts
      with it and the limiter would be off).
    * Any other prefix matches as either a literal equal or a
      ``prefix + "/" + something`` so ``/telephony/webhooks`` covers
      ``/telephony/webhooks/voice`` but does not accidentally cover
      ``/telephony/webhookspoof``.
    """

    for prefix in _exempt_prefixes():
        if prefix == "/":
            if path == "/":
                return True
            continue
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _identity(request: Request) -> tuple[str, str]:
    """Return (kind, value) used to build the limiter key.

    Tries the JWT first so authenticated users get their own bucket;
    falls back to client IP. ``kind`` is included in the key so a user
    and an unrelated IP can't accidentally collide.
    """

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        try:
            payload = decode_token(token)
            if payload and payload.get("sub"):
                return "user", str(payload["sub"])
        except Exception:
            pass
    ip = request.client.host if request.client else "unknown"
    return "ip", ip


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        method = request.method.upper()
        path = request.url.path

        # CORS preflights are issued automatically by browsers and would
        # otherwise count against the same budget as the real request.
        if method == "OPTIONS":
            return await call_next(request)

        if _is_exempt(path):
            return await call_next(request)

        identity_kind, identity_value = _identity(request)

        # Pick the right bucket. Auth endpoints have a much smaller
        # budget so a single IP cannot brute-force credentials.
        # Expensive AI inference and telephony endpoints have their own
        # narrower budgets to prevent runaway cost amplification.
        if path in _AUTH_PATHS:
            bucket = "auth"
            max_requests = settings.RATE_LIMIT_AUTH_REQUESTS
            window = settings.RATE_LIMIT_AUTH_WINDOW_SECONDS
        elif method == "POST" and path in _AI_INFERENCE_PATHS:
            bucket = "ai"
            max_requests = settings.RATE_LIMIT_AI_REQUESTS
            window = settings.RATE_LIMIT_AI_WINDOW_SECONDS
        elif method == "POST" and path == _TELEPHONY_ORIGINATE_PATH:
            bucket = "telephony"
            max_requests = settings.RATE_LIMIT_TELEPHONY_REQUESTS
            window = settings.RATE_LIMIT_TELEPHONY_WINDOW_SECONDS
        elif method == "POST" and path == _CAMPAIGN_ACTIVATE_PATH:
            bucket = "campaign_activate"
            max_requests = settings.RATE_LIMIT_CAMPAIGN_ACTIVATE_REQUESTS
            window = settings.RATE_LIMIT_CAMPAIGN_ACTIVATE_WINDOW_SECONDS
        else:
            bucket = "api"
            max_requests = settings.RATE_LIMIT_REQUESTS
            window = settings.RATE_LIMIT_WINDOW_SECONDS

        key = f"rl:{bucket}:{identity_kind}:{identity_value}"

        try:
            await limit_async(key, max_requests=max_requests, window=window)
        except HTTPException as exc:
            log.warning(
                "rate_limit.exceeded",
                bucket=bucket,
                identity_kind=identity_kind,
                path=path,
            )
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
            )

        return await call_next(request)
