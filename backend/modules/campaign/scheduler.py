"""Automatic call-scheduling engine for campaigns.

This is the brain behind the per-minute Celery Beat tick. It is written as a
plain service operating on a SQLAlchemy ``Session`` so it can be driven both
from the Celery task (production) and directly from tests (no broker needed).

Each tick does three things, globally across all organizations:

1. **Auto-activation** — ``scheduled`` campaigns whose ``scheduled_at`` has
   arrived are activated (reusing :meth:`CampaignService.activate`, which also
   enforces the future-time + business-hours guards). Campaigns outside their
   business-hours window stay ``scheduled`` and are retried on a later tick.
2. **Paced dispatch** — for ``active`` campaigns inside their business-hours
   window, a pacing budget (``calls_per_hour`` + ``max_concurrent_calls``)
   decides how many ``queued`` executions get dispatched this tick.
3. **Completion** — ``active`` campaigns whose executions are all terminal flip
   to ``completed``.

``paused`` campaigns are skipped entirely (manual pause), and resume simply
flips them back to ``active`` so the next tick picks them up again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.logging import get_logger
from config.settings import settings
from modules.campaign.execution_model import Execution
from modules.campaign.model import (
    CAMPAIGN_STATUS_ACTIVE,
    CAMPAIGN_STATUS_COMPLETED,
    CAMPAIGN_STATUS_SCHEDULED,
    Campaign,
)
from modules.campaign.repository import ExecutionRepository, WorkflowRepository
from modules.campaign.scheduling import (
    is_within_business_hours,
    next_business_window,
    pacing_allowance,
)
from modules.campaign.workflow_model import Workflow

log = get_logger("campaign.scheduler")

# Execution lifecycle vocabulary (plain strings, matching the worker).
EXEC_QUEUED = "queued"
EXEC_RUNNING = "running"
EXEC_COMPLETED = "completed"
EXEC_FAILED = "failed"
_TERMINAL = (EXEC_COMPLETED, EXEC_FAILED)


def _default_dispatcher(db: Session, executions: list[Execution]) -> None:
    """Dispatch each due execution.

    Dial-candidate lead executions are originated by the FastAPI process over
    authenticated internal HTTP (see :func:`modules.campaign.worker.
    dispatch_execution`) so the realtime AI agent (LiveKit room + STT/LLM/TTS
    + SIP bridge) runs on the long-running uvicorn event loop instead of the
    short-lived Celery ``asyncio.run`` loop. Legacy / non-dial executions
    still run in-process.

    Imported lazily so the engine (and its tests) don't pull the OpenAI /
    HTTP machinery unless an execution is actually dispatched.
    """

    from modules.campaign.worker import dispatch_execution

    for execution in executions:
        dispatch_execution(db, execution)


def _resolve_pacing(campaign: Campaign) -> tuple[int, int]:
    cph = campaign.calls_per_hour
    if cph is None:
        cph = settings.CAMPAIGN_DEFAULT_CALLS_PER_HOUR
    mcc = campaign.max_concurrent_calls
    if mcc is None:
        mcc = settings.CAMPAIGN_DEFAULT_MAX_CONCURRENT_CALLS
    return int(cph), int(mcc)


class CampaignScheduler:
    """Stateless engine; all state lives in the DB."""

    # ------------------------------------------------------------------ #
    # Per-campaign execution bookkeeping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _status_counts(db: Session, campaign_id) -> dict[str, int]:
        return ExecutionRepository.count_by_status(db, campaign_id)

    @staticmethod
    def _dispatched_last_hour(db: Session, campaign_id, now: datetime) -> int:
        cutoff = now - timedelta(hours=1)
        return ExecutionRepository.count_dispatched_since(db, campaign_id, cutoff)

    @staticmethod
    def _active_workflow(db: Session, campaign_id) -> Workflow | None:
        return WorkflowRepository.get_active_for_campaign(db, campaign_id)

    # ------------------------------------------------------------------ #
    # Retry bookkeeping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _scheduled_retry_count(db: Session, campaign_id) -> int:
        """Executions parked waiting for a future retry (any time)."""
        return ExecutionRepository.count_scheduled_retries(db, campaign_id)

    @staticmethod
    def _requeue_due_retries(
        db: Session, campaign_id, now: datetime
    ) -> int:
        """Flip due scheduled retries back to ``queued`` for re-dispatch.

        Only retries whose ``next_retry_at`` has arrived are requeued; the
        caller gates this on the campaign being inside its business-hours
        window so retries respect the calling schedule. Pacing and concurrency
        are enforced afterwards by the normal paced-dispatch step.
        """
        requeued = ExecutionRepository.requeue_due_retries(db, campaign_id, now)
        if requeued:
            db.commit()
        return requeued

    @staticmethod
    def _retry_stats(db: Session, campaign_id) -> dict:
        """Aggregate retry counters for a campaign in a single query."""
        return ExecutionRepository.retry_stats(db, campaign_id)

    @staticmethod
    def retries(db: Session, campaign: Campaign) -> dict:
        """Campaign-level retry summary for ``GET /campaigns/{id}/retries``."""

        stats = CampaignScheduler._retry_stats(db, campaign.id)
        return {
            "campaign_id": str(campaign.id),
            "total_retries": stats["total_retries"],
            "pending_retries": stats["pending_retries"],
            "exhausted_retries": stats["exhausted_retries"],
            "successful_retries": stats["successful_retries"],
        }

    @staticmethod
    def retry_history(db: Session, execution: Execution) -> dict:
        """Per-attempt history for ``GET .../executions/{id}/retry-history``.

        The trail is appended by the retry engine into the execution context;
        the current row state is always included as the latest known attempt.
        """

        ctx = execution.context or {}
        history = list(ctx.get("retry_history") or [])
        return {
            "execution_id": str(execution.id),
            "attempt_number": execution.attempt_number,
            "retry_status": execution.retry_status,
            "outcome": execution.outcome,
            "last_failure_reason": execution.last_failure_reason,
            "next_retry_at": (
                execution.next_retry_at.isoformat()
                if execution.next_retry_at
                else None
            ),
            "attempts": [
                {
                    "attempt_number": h.get("attempt_number"),
                    "failure_reason": h.get("failure_reason"),
                    "retry_time": h.get("next_retry_at"),
                    "ran_at": h.get("ran_at"),
                    "outcome": h.get("outcome"),
                }
                for h in history
            ],
        }

    # ------------------------------------------------------------------ #
    # Public: metrics + schedule status (used by the API + tick)
    # ------------------------------------------------------------------ #

    @staticmethod
    def metrics(db: Session, campaign: Campaign) -> dict:
        counts = CampaignScheduler._status_counts(db, campaign.id)
        queued = counts.get(EXEC_QUEUED, 0)
        active = counts.get(EXEC_RUNNING, 0)
        completed = counts.get(EXEC_COMPLETED, 0)
        failed = counts.get(EXEC_FAILED, 0)
        enqueued_total = queued + active + completed + failed
        terminal = completed + failed

        # ``failed`` (status) also covers rows parked waiting for a retry
        # (retry_status=scheduled). ``failed_executions`` is the count of
        # *terminally* failed executions (no further retry: None/exhausted).
        scheduled_retries = CampaignScheduler._scheduled_retry_count(
            db, campaign.id
        )
        failed_executions = max(0, failed - scheduled_retries)

        total_leads = 0
        if campaign.lead_list_id is not None:
            from modules.leads.model import lead_list_memberships

            total_leads = int(
                db.execute(
                    select(func.count())
                    .select_from(lead_list_memberships)
                    .where(
                        lead_list_memberships.c.lead_list_id
                        == campaign.lead_list_id
                    )
                ).scalar_one()
            )

        # Leads never enqueued yet (e.g. capped activation or not-yet-active).
        pending = max(0, total_leads - enqueued_total)
        denom = total_leads if total_leads else enqueued_total
        progress = round((terminal / denom) * 100, 1) if denom else 0.0

        try:
            retry_stats = CampaignScheduler._retry_stats(db, campaign.id)
        except Exception:
            db.rollback()
            retry_stats = {
                "total_retries": 0,
                "retry_success_rate": 0.0,
                "exhausted_retries": 0,
                "average_attempts_per_call": 0.0,
            }

        try:
            voicemail_stats = CampaignScheduler._voicemail_stats(db, campaign.id)
        except Exception:
            # Graceful fallback if AMD columns haven't been migrated yet.
            db.rollback()
            voicemail_stats = {
                "human_answered": 0,
                "voicemail_detected": 0,
                "voicemail_dropped": 0,
                "voicemail_retry_count": 0,
                "voicemail_success_rate": 0.0,
            }

        return {
            "campaign_id": str(campaign.id),
            "status": campaign.status,
            "total_leads": total_leads,
            "queued_leads": queued,
            "active_calls": active,
            "completed_calls": completed,
            "failed_calls": failed,
            "failed_executions": failed_executions,
            "pending_leads": pending,
            "progress_percent": progress,
            # Retry-engine metrics.
            "retry_count": retry_stats["total_retries"],
            "retry_success_rate": retry_stats["retry_success_rate"],
            "exhausted_retries": retry_stats["exhausted_retries"],
            "average_attempts_per_call": retry_stats[
                "average_attempts_per_call"
            ],
            # AMD / Voicemail-drop metrics.
            "human_answered": voicemail_stats["human_answered"],
            "voicemail_detected": voicemail_stats["voicemail_detected"],
            "voicemail_dropped": voicemail_stats["voicemail_dropped"],
            "voicemail_retry_count": voicemail_stats["voicemail_retry_count"],
            "voicemail_success_rate": voicemail_stats[
                "voicemail_success_rate"
            ],
        }

    @staticmethod
    def _voicemail_stats(db: Session, campaign_id) -> dict:
        """AMD / voicemail-drop counters for a campaign (from telephony_calls)."""

        from modules.telephony.repository import TelephonyCallRepository

        return TelephonyCallRepository.voicemail_metrics(db, campaign_id)

    @staticmethod
    def schedule_status(db: Session, campaign: Campaign) -> dict:
        now = datetime.now(timezone.utc)
        within = is_within_business_hours(
            campaign.business_hours, campaign.timezone, now
        )
        nxt = next_business_window(
            campaign.business_hours, campaign.timezone, now
        )
        due = (
            campaign.scheduled_at is None
            or campaign.scheduled_at <= now
        )
        cph, mcc = _resolve_pacing(campaign)
        return {
            "campaign_id": str(campaign.id),
            "status": campaign.status,
            "scheduled_at": (
                campaign.scheduled_at.isoformat()
                if campaign.scheduled_at
                else None
            ),
            "timezone": campaign.timezone,
            "server_time_utc": now.isoformat(),
            "is_due": bool(due),
            "within_business_hours": bool(within),
            "next_business_window": (
                nxt.isoformat() if nxt is not None else None
            ),
            "pacing": {
                "calls_per_hour": cph,
                "max_concurrent_calls": mcc,
            },
        }

    # ------------------------------------------------------------------ #
    # The tick
    # ------------------------------------------------------------------ #

    @staticmethod
    def tick(
        db: Session,
        *,
        now: datetime | None = None,
        dispatcher=None,
    ) -> dict:
        """Advance every campaign one step. Returns a summary for logging."""

        now = now or datetime.now(timezone.utc)
        dispatcher = dispatcher or _default_dispatcher

        activated = CampaignScheduler._activate_due(db, now)
        dispatched, completed = CampaignScheduler._advance_active(
            db, now, dispatcher
        )

        summary = {
            "activated": activated,
            "dispatched": dispatched,
            "completed": completed,
            "at": now.isoformat(),
        }
        if activated or dispatched or completed:
            log.info("campaign.scheduler.tick", **summary)
        return summary

    @staticmethod
    def _activate_due(db: Session, now: datetime) -> int:
        """Activate ``scheduled`` campaigns whose start time has arrived."""

        from modules.campaign.service import CampaignService

        scheduled = list(
            db.execute(
                select(Campaign).where(
                    Campaign.status == CAMPAIGN_STATUS_SCHEDULED
                )
            ).scalars()
        )

        activated = 0
        for campaign in scheduled:
            # Future start time -> not yet due.
            if campaign.scheduled_at is not None and campaign.scheduled_at > now:
                continue
            # ``activate`` re-checks business hours and leaves the campaign
            # ``scheduled`` (deferred) when outside the window.
            result = CampaignService.activate(db, campaign)
            if result.get("state") == CAMPAIGN_STATUS_ACTIVE:
                activated += 1
        return activated

    @staticmethod
    def _advance_active(db: Session, now: datetime, dispatcher) -> tuple[int, int]:
        """Pace dispatch + detect completion for ``active`` campaigns."""

        active_campaigns = list(
            db.execute(
                select(Campaign).where(
                    Campaign.status == CAMPAIGN_STATUS_ACTIVE
                )
            ).scalars()
        )

        total_dispatched = 0
        total_completed = 0

        for campaign in active_campaigns:
            within_hours = is_within_business_hours(
                campaign.business_hours, campaign.timezone, now
            )

            # Requeue retries whose backoff has elapsed, but only inside the
            # calling window so retries respect business hours. Outside the
            # window they stay ``scheduled`` and are picked up on a later tick.
            if within_hours:
                CampaignScheduler._requeue_due_retries(db, campaign.id, now)

            counts = CampaignScheduler._status_counts(db, campaign.id)
            queued = counts.get(EXEC_QUEUED, 0)
            running = counts.get(EXEC_RUNNING, 0)
            enqueued_total = sum(counts.values())
            scheduled_retries = CampaignScheduler._scheduled_retry_count(
                db, campaign.id
            )

            # Completion: something ran, nothing is queued/running, and no
            # retries are still parked waiting for their backoff to elapse.
            if (
                enqueued_total > 0
                and queued == 0
                and running == 0
                and scheduled_retries == 0
            ):
                campaign.status = CAMPAIGN_STATUS_COMPLETED
                workflow = CampaignScheduler._active_workflow(db, campaign.id)
                if workflow is not None:
                    workflow.state = "completed"
                db.commit()
                total_completed += 1
                continue

            if queued == 0:
                continue

            # Respect the calling window — defer to the next valid one.
            if not within_hours:
                continue

            cph, mcc = _resolve_pacing(campaign)
            dispatched_last_hour = CampaignScheduler._dispatched_last_hour(
                db, campaign.id, now
            )
            allowance = pacing_allowance(
                calls_per_hour=cph,
                max_concurrent_calls=mcc,
                running_now=running,
                dispatched_last_hour=dispatched_last_hour,
                tick_seconds=settings.CAMPAIGN_SCHEDULER_INTERVAL_SECONDS,
            )
            if allowance <= 0:
                continue

            workflow = CampaignScheduler._active_workflow(db, campaign.id)
            if workflow is None:
                continue

            batch = ExecutionRepository.list_queued(
                db, workflow.id, limit=allowance, now=now
            )
            if not batch:
                continue

            dispatcher(db, batch)
            total_dispatched += len(batch)

        return total_dispatched, total_completed
