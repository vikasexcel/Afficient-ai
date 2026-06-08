"""Production-grade ASGI middleware: correlation IDs and global error handling.

Provides two additions to every HTTP request/response cycle:

1. **CorrelationIdMiddleware** — attaches a ``X-Request-ID`` header to every
   request (generating one when missing) and echoes it back in the response.
   The ID is stored in a ``contextvars.ContextVar`` so structured-log calls
   anywhere in the request lifecycle can include it automatically.

2. **global_exception_handler** — FastAPI ``@app.exception_handler(Exception)``
   that converts unhandled exceptions into a consistent JSON envelope instead
   of leaking stack traces or returning non-JSON 500s:

       {"detail": "Internal server error", "request_id": "<id>"}

   The full traceback is always logged at ERROR level with the request_id so
   production logs are searchable without exposing internals to callers.
"""

from __future__ import annotations

import traceback
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from common.logging import get_logger

log = get_logger("middleware")

# ---------------------------------------------------------------------------
# Context variable — available anywhere in the same async task/call stack
# ---------------------------------------------------------------------------

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Return the current request's correlation ID (empty string if outside a request)."""
    return _request_id_var.get("")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

REQUEST_ID_HEADER = "X-Request-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID to every request and echo it in the response.

    * If the caller provides ``X-Request-ID``, that value is used (sanitised
      to 128 chars max to prevent log-injection attacks).
    * Otherwise a new UUID4 is generated.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        raw = request.headers.get(REQUEST_ID_HEADER, "")
        # Sanitise: take only printable ASCII, truncate
        request_id = "".join(c for c in raw if c.isprintable())[:128] or str(
            uuid.uuid4()
        )

        token = _request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            _request_id_var.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


# ---------------------------------------------------------------------------
# Global exception handler (registered in main.py)
# ---------------------------------------------------------------------------


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions.

    Logs a full traceback at ERROR level (including request_id and path) and
    returns a clean JSON 500 that doesn't expose implementation details.
    """
    request_id = get_request_id() or request.headers.get(REQUEST_ID_HEADER, "unknown")

    log.error(
        "unhandled_exception",
        request_id=request_id,
        method=request.method,
        path=str(request.url.path),
        exc_type=type(exc).__name__,
        traceback=traceback.format_exc(),
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request_id,
        },
        headers={REQUEST_ID_HEADER: request_id},
    )
