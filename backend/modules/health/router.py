"""Health and readiness endpoints — Phase 5B hardened version.

Two endpoints:

* ``GET /health``  — **liveness probe**.  Returns 200 when the process is
  alive.  Does NOT check external dependencies (DB, Redis, Celery) so it
  never causes an unhealthy process to be killed while transient infra
  blips occur.  Load balancers / k8s should use this for liveness.

* ``GET /health/ready`` — **readiness probe**.  Performs lightweight checks
  against PostgreSQL, Redis, and the Celery scheduler.  Returns 200 only
  when all required components are reachable.  Load balancers should route
  traffic away from an instance that returns non-200 here.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from common.logging import get_logger

log = get_logger("health")

router = APIRouter()

# ---------------------------------------------------------------------------
# Liveness — always 200 while the process is alive
# ---------------------------------------------------------------------------


@router.get("/health", include_in_schema=True)
async def liveness():
    """Process liveness probe — always 200 when the app is running."""
    return {"status": "ok", "service": "backend"}


# ---------------------------------------------------------------------------
# Readiness — checks DB, Redis, and scheduler
# ---------------------------------------------------------------------------


@router.get("/health/ready", include_in_schema=True)
async def readiness():
    """Readiness probe — 200 only when all required services are reachable.

    Checks:
    * PostgreSQL — executes ``SELECT 1``
    * Redis — executes ``PING``
    * Celery scheduler — reads last scheduler tick from Redis
    """

    checks: dict[str, dict] = {}
    healthy = True
    t0 = time.monotonic()

    # ------------------------------------------------------------------ #
    # PostgreSQL
    # ------------------------------------------------------------------ #
    try:
        from database.session import SessionLocal

        db = SessionLocal()
        try:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
            checks["postgres"] = {"status": "ok"}
        finally:
            db.close()
    except Exception as exc:
        checks["postgres"] = {"status": "error", "detail": str(exc)[:200]}
        healthy = False

    # ------------------------------------------------------------------ #
    # Redis
    # ------------------------------------------------------------------ #
    try:
        import redis

        from config.settings import settings

        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = {"status": "ok"}
        r.close()
    except Exception as exc:
        checks["redis"] = {"status": "error", "detail": str(exc)[:200]}
        healthy = False

    # ------------------------------------------------------------------ #
    # Celery scheduler (best-effort — not required for readiness)
    # ------------------------------------------------------------------ #
    try:
        from modules.campaign.scheduler_diagnostics import scheduler_status
        from database.session import SessionLocal

        db = SessionLocal()
        try:
            sched = scheduler_status(db)
            if sched["scheduler_online"]:
                checks["scheduler"] = {
                    "status": "ok",
                    "last_tick": sched.get("last_tick"),
                }
            else:
                checks["scheduler"] = {
                    "status": "degraded",
                    "message": sched.get("message", "offline"),
                }
                # Scheduler offline is WARNING, not ERROR — the API still works.
        finally:
            db.close()
    except Exception as exc:
        checks["scheduler"] = {"status": "error", "detail": str(exc)[:200]}

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    status = "ok" if healthy else "degraded"

    payload = {
        "status": status,
        "elapsed_ms": elapsed_ms,
        "checks": checks,
    }

    if not healthy:
        log.warning("health.readiness_degraded", checks=checks)
        return JSONResponse(status_code=503, content=payload)

    return payload
