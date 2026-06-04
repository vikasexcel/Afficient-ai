"""Celery application + Beat schedule for the campaign scheduling engine.

Run the worker + beat together in development::

    celery -A modules.campaign.celery_app:celery_app worker --beat -l info

or as separate processes in production (recommended)::

    celery -A modules.campaign.celery_app:celery_app worker -l info
    celery -A modules.campaign.celery_app:celery_app beat   -l info

Broker / backend default to ``REDIS_URL`` so a single Redis instance backs
memory, rate limiting and the task queue unless overridden.
"""

from __future__ import annotations

from celery import Celery

from config.settings import settings

_broker = settings.CELERY_BROKER_URL or settings.REDIS_URL
_backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

celery_app = Celery(
    "aifficient",
    broker=_broker,
    backend=_backend,
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "campaign-scheduler-tick": {
            "task": "campaign.scheduler_tick",
            "schedule": settings.CAMPAIGN_SCHEDULER_INTERVAL_SECONDS,
        },
    },
)

# Register tasks (import for side effects). Kept at the bottom to avoid a
# circular import: ``tasks`` imports ``celery_app`` from this module.
from modules.campaign import tasks as _tasks  # noqa: E402,F401
