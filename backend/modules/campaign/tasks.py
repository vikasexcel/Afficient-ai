"""Celery tasks for the campaign call-scheduling engine.

These are thin wrappers around :class:`CampaignScheduler`. All the real logic
(and all the tests) live in :mod:`modules.campaign.scheduler`, so the tasks
just manage a DB session lifecycle around each call.
"""

from __future__ import annotations

from common.logging import get_logger
from database.session import SessionLocal
from modules.campaign.celery_app import celery_app
from modules.campaign.scheduler import CampaignScheduler

log = get_logger("campaign.tasks")


@celery_app.task(name="campaign.scheduler_tick")
def scheduler_tick() -> dict:
    """Beat-driven tick: activate due campaigns + pace dispatch (every minute)."""

    db = SessionLocal()
    try:
        return CampaignScheduler.tick(db)
    except Exception as exc:  # pragma: no cover - safety net for the worker
        db.rollback()
        log.warning("campaign.scheduler_tick.failed", error=str(exc))
        raise
    finally:
        db.close()
