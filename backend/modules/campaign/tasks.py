"""Celery tasks for the campaign call-scheduling engine.

These are thin wrappers around :class:`CampaignScheduler`. All the real logic
(and all the tests) live in :mod:`modules.campaign.scheduler`, so the tasks
just manage a DB session lifecycle around each call.
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis

from common.logging import get_logger
from config.settings import settings
from database.session import SessionLocal
from modules.campaign.celery_app import celery_app
from modules.campaign.scheduler import CampaignScheduler
from modules.campaign.scheduler_keys import BEAT_HEARTBEAT_KEY, LAST_TICK_KEY

log = get_logger("campaign.tasks")


def _redis_client() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)


def _stamp_redis(key: str) -> None:
    """Best-effort timestamp write for scheduler diagnostics."""

    try:
        _redis_client().set(
            key,
            datetime.now(timezone.utc).isoformat(),
            ex=86400,
        )
    except Exception as exc:  # pragma: no cover - diagnostics only
        log.warning("campaign.scheduler_redis_stamp.failed", key=key, error=str(exc))


@celery_app.task(name="campaign.beat_heartbeat")
def beat_heartbeat() -> dict:
    """Lightweight Beat liveness signal for ``scheduler-status``."""

    _stamp_redis(BEAT_HEARTBEAT_KEY)
    return {"ok": True}


@celery_app.task(name="campaign.scheduler_tick")
def scheduler_tick() -> dict:
    """Beat-driven tick: activate due campaigns + pace dispatch (every minute)."""

    db = SessionLocal()
    try:
        summary = CampaignScheduler.tick(db)
        _stamp_redis(LAST_TICK_KEY)
        return summary
    except Exception as exc:  # pragma: no cover - safety net for the worker
        db.rollback()
        log.warning("campaign.scheduler_tick.failed", error=str(exc))
        raise
    finally:
        db.close()
