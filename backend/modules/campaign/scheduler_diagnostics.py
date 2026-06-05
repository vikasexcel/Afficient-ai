"""Operational diagnostics for the Celery campaign scheduler.

Used by ``GET /campaigns/scheduler-status`` and startup warnings. Detects
whether Redis, a Celery worker, and Celery Beat are healthy enough to drain
queued campaign executions.
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import settings
from modules.campaign.execution_model import Execution
from modules.campaign.scheduler_keys import BEAT_HEARTBEAT_KEY, LAST_TICK_KEY

# Beat emits a heartbeat every 30 s; treat as offline after ~3 missed beats.
BEAT_STALE_SECONDS = 90.0
# Scheduler tick runs every ``CAMPAIGN_SCHEDULER_INTERVAL_SECONDS``; allow
# ~2.5 intervals before reporting a stale last tick.
TICK_STALE_SECONDS = settings.CAMPAIGN_SCHEDULER_INTERVAL_SECONDS * 2.5

_INSPECT_TIMEOUT = 1.5


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _redis_ping() -> tuple[bool, str | None]:
    try:
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        client.ping()
        return True, None
    except Exception as exc:  # pragma: no cover - broker down
        return False, str(exc)


def _worker_running() -> bool:
    try:
        from modules.campaign.celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=_INSPECT_TIMEOUT)
        ping = inspect.ping()
        return bool(ping)
    except Exception:
        return False


def _beat_running() -> bool:
    try:
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        raw = client.get(BEAT_HEARTBEAT_KEY)
        if raw is None:
            return False
        ts = _parse_iso(raw.decode() if isinstance(raw, bytes) else raw)
        if ts is None:
            return False
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age <= BEAT_STALE_SECONDS
    except Exception:
        return False


def _last_scheduler_tick() -> str | None:
    try:
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        raw = client.get(LAST_TICK_KEY)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw
    except Exception:
        return None


def _execution_counts(db: Session) -> tuple[int, int]:
    rows = db.execute(
        select(Execution.status, func.count()).group_by(Execution.status)
    ).all()
    counts = {status: int(n) for status, n in rows}
    return counts.get("queued", 0), counts.get("running", 0)


def scheduler_status(db: Session) -> dict:
    """Build the scheduler diagnostics payload."""

    redis_ok, redis_error = _redis_ping()
    worker_ok = _worker_running() if redis_ok else False
    beat_ok = _beat_running() if redis_ok else False
    queued, active = _execution_counts(db)
    last_tick = _last_scheduler_tick()

    scheduler_online = redis_ok and worker_ok and beat_ok
    tick_ts = _parse_iso(last_tick)
    tick_recent = (
        tick_ts is not None
        and (datetime.now(timezone.utc) - tick_ts).total_seconds()
        <= TICK_STALE_SECONDS
    )

    return {
        "worker_running": worker_ok,
        "beat_running": beat_ok,
        "redis_connected": redis_ok,
        "scheduler_online": scheduler_online,
        "queued_executions": queued,
        "queued_execution_count": queued,
        "active_executions": active,
        "last_scheduler_tick": last_tick,
        "last_tick": last_tick,
        "last_tick_recent": tick_recent,
        "scheduler_interval_seconds": settings.CAMPAIGN_SCHEDULER_INTERVAL_SECONDS,
        "redis_error": redis_error,
        "message": _status_message(
            redis_ok=redis_ok,
            worker_ok=worker_ok,
            beat_ok=beat_ok,
            queued=queued,
            tick_recent=tick_recent,
        ),
    }


def _status_message(
    *,
    redis_ok: bool,
    worker_ok: bool,
    beat_ok: bool,
    queued: int,
    tick_recent: bool,
) -> str:
    if not redis_ok:
        return "Redis broker unreachable; campaign calls cannot be dispatched."
    if not beat_ok:
        return (
            "Celery Beat is not running; queued executions will not be "
            "scheduled for dispatch."
        )
    if not worker_ok:
        return (
            "Celery worker is not running; scheduled executions will not "
            "be dialed."
        )
    if queued > 0 and not tick_recent:
        return (
            f"{queued} execution(s) queued but the scheduler has not ticked "
            "recently; check worker logs."
        )
    if queued > 0:
        return f"Scheduler online; {queued} execution(s) awaiting dispatch."
    return "Scheduler online; no queued executions."
