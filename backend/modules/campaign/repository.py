import uuid
from datetime import datetime

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.orm import Session

from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.retry import (
    RETRY_STATUS_COMPLETED,
    RETRY_STATUS_EXHAUSTED,
    RETRY_STATUS_PENDING,
    RETRY_STATUS_SCHEDULED,
)
from modules.campaign.workflow_model import Workflow
from modules.leads.model import Lead, LeadList, lead_list_memberships
from modules.playbook.model import Playbook

# ---------------------------------------------------------------------------
# Internal constants — execution lifecycle status vocabulary.
# Mirrors the string constants defined in scheduler.py and worker.py.
# ---------------------------------------------------------------------------
_EXEC_QUEUED = "queued"
_EXEC_RUNNING = "running"
_EXEC_COMPLETED = "completed"
_EXEC_FAILED = "failed"

# ---------------------------------------------------------------------------
# Subquery alias for lead count via the memberships join table.
# ---------------------------------------------------------------------------
_membership_count = (
    select(
        lead_list_memberships.c.lead_list_id,
        func.count(lead_list_memberships.c.lead_id).label("lead_count"),
    )
    .group_by(lead_list_memberships.c.lead_list_id)
    .subquery("_membership_count")
)


class CampaignRepository:
    @staticmethod
    def create(db, campaign):
        db.add(campaign)
        db.flush()
        return campaign

    @staticmethod
    def get(
        db: Session,
        organization_id: uuid.UUID,
        campaign_id: uuid.UUID,
    ) -> Campaign | None:
        stmt = select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.organization_id == organization_id,
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def list_by_org(
        db: Session,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[Campaign], int]:
        base = select(Campaign).where(
            Campaign.organization_id == organization_id
        )
        if status is not None:
            base = base.where(Campaign.status == status)

        total = db.execute(
            select(func.count()).select_from(base.subquery())
        ).scalar_one()

        stmt = (
            base.order_by(Campaign.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list(db.execute(stmt).scalars())
        return rows, int(total)

    @staticmethod
    def delete(db: Session, campaign: Campaign) -> None:
        # The campaign's child rows (workflows + their executions) use plain
        # FKs with no ON DELETE cascade, so deleting the campaign directly
        # raises an IntegrityError once it has been activated. Remove the
        # children first, deepest first, then the campaign itself.
        workflow_ids = [
            row[0]
            for row in db.execute(
                select(Workflow.id).where(
                    Workflow.campaign_id == campaign.id
                )
            ).all()
        ]
        if workflow_ids:
            db.execute(
                delete(Execution).where(
                    Execution.workflow_id.in_(workflow_ids)
                )
            )
            db.execute(
                delete(Workflow).where(Workflow.id.in_(workflow_ids))
            )
        db.delete(campaign)

    # ------------------------------------------------------------------ #
    # Enrichment helpers for the listing UI
    # ------------------------------------------------------------------ #

    @staticmethod
    def playbook_names(
        db: Session, ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        rows = db.execute(
            select(Playbook.id, Playbook.name).where(Playbook.id.in_(ids))
        ).all()
        return {r[0]: r[1] for r in rows}

    @staticmethod
    def lead_list_info(
        db: Session, ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[str, int]]:
        if not ids:
            return {}
        rows = db.execute(
            select(
                LeadList.id,
                LeadList.name,
                func.coalesce(_membership_count.c.lead_count, 0).label(
                    "lead_count"
                ),
            )
            .outerjoin(
                _membership_count,
                _membership_count.c.lead_list_id == LeadList.id,
            )
            .where(LeadList.id.in_(ids))
        ).all()
        return {r[0]: (r[1], int(r[2])) for r in rows}

    @staticmethod
    def leads_for_list(
        db: Session,
        organization_id: uuid.UUID,
        lead_list_id: uuid.UUID,
        *,
        limit: int = 1000,
    ) -> list[Lead]:
        stmt = (
            select(Lead)
            .where(
                Lead.organization_id == organization_id,
                Lead.id.in_(
                    select(lead_list_memberships.c.lead_id).where(
                        lead_list_memberships.c.lead_list_id == lead_list_id
                    )
                ),
            )
            .order_by(Lead.created_at.asc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars())


class WorkflowRepository:
    """Data-access layer for the ``workflows`` table.

    All SQLAlchemy queries touching ``workflows`` (or joins that start from
    ``workflows``) live here.  Callers (service, scheduler, router) receive
    ORM objects and call ``db.commit()`` themselves — the repository only
    flushes.
    """

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    @staticmethod
    def create(db: Session, workflow: Workflow) -> Workflow:
        db.add(workflow)
        db.flush()
        return workflow

    @staticmethod
    def update_state(db: Session, workflow: Workflow, state: str) -> Workflow:
        """Set ``workflow.state`` and flush (caller commits)."""
        workflow.state = state
        db.flush()
        return workflow

    @staticmethod
    def update_graph(
        db: Session, workflow: Workflow, nodes: list, edges: list
    ) -> Workflow:
        """Replace the graph definition on a workflow (Phase 2C)."""
        workflow.nodes = nodes
        workflow.edges = edges
        db.flush()
        return workflow

    # ------------------------------------------------------------------ #
    # Single-row reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def get(db: Session, workflow_id: uuid.UUID) -> Workflow | None:
        """Fetch a workflow by primary key (no tenant check)."""
        return db.execute(
            select(Workflow).where(Workflow.id == workflow_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_for_org(
        db: Session, org_id: uuid.UUID, workflow_id: uuid.UUID
    ) -> Workflow | None:
        """Fetch a workflow scoped to an organisation (via its campaign)."""
        return db.execute(
            select(Workflow)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Workflow.id == workflow_id,
                Campaign.organization_id == org_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def get_active_for_campaign(
        db: Session, campaign_id, *, lock: bool = False
    ) -> Workflow | None:
        """Return the single active workflow for a campaign, if one exists.

        Pass ``lock=True`` to acquire a ``SELECT … FOR UPDATE SKIP LOCKED``
        row-lock (used by the idempotency guard in ``CampaignService.activate``
        to prevent duplicate activation under concurrent requests).
        """
        stmt = (
            select(Workflow)
            .where(
                Workflow.campaign_id == campaign_id,
                Workflow.state == "active",
            )
            .order_by(Workflow.created_at.desc())
        )
        if lock:
            stmt = stmt.with_for_update(skip_locked=True)
        return db.execute(stmt).scalars().first()

    @staticmethod
    def get_latest_for_campaign(
        db: Session, campaign_id
    ) -> Workflow | None:
        """Return the most-recently created workflow for a campaign, any state."""
        return db.execute(
            select(Workflow)
            .where(Workflow.campaign_id == campaign_id)
            .order_by(Workflow.created_at.desc())
        ).scalars().first()

    @staticmethod
    def get_paused_for_campaign(
        db: Session, campaign_id
    ) -> Workflow | None:
        """Return the most-recently paused workflow for a campaign."""
        return db.execute(
            select(Workflow)
            .where(
                Workflow.campaign_id == campaign_id,
                Workflow.state == "paused",
            )
            .order_by(Workflow.created_at.desc())
        ).scalars().first()

    # ------------------------------------------------------------------ #
    # Collection reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_by_campaign(
        db: Session, campaign_id
    ) -> list[Workflow]:
        """All workflows for a campaign, newest first."""
        return list(
            db.execute(
                select(Workflow)
                .where(Workflow.campaign_id == campaign_id)
                .order_by(Workflow.created_at.desc())
            ).scalars()
        )

    # ------------------------------------------------------------------ #
    # Subquery helpers (no session required — returns a Select object)
    # ------------------------------------------------------------------ #

    @staticmethod
    def ids_subquery(campaign_id):
        """Return a correlated SELECT subquery of workflow ids for a campaign.

        Used in bulk UPDATE statements to avoid a separate round-trip for
        workflow ids (e.g. ``Execution.workflow_id.in_(ids_subquery(…))``).
        """
        return select(Workflow.id).where(Workflow.campaign_id == campaign_id)


class ExecutionRepository:
    """Data-access layer for the ``executions`` table.

    All SQLAlchemy queries touching ``executions`` live here.  Callers
    receive ORM objects or primitive counts and commit themselves.
    """

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    @staticmethod
    def create(db: Session, execution: Execution) -> Execution:
        db.add(execution)
        db.flush()
        return execution

    @staticmethod
    def update_current_node(
        db: Session, execution: Execution, node_id: str | None
    ) -> Execution:
        """Advance an execution to a different graph node (Phase 2C)."""
        execution.current_node_id = node_id
        db.flush()
        return execution

    @staticmethod
    def update_outputs(
        db: Session, execution: Execution, node_id: str, output: dict
    ) -> Execution:
        """Accumulate per-node output in the ``node_outputs`` map (Phase 2C)."""
        outputs = dict(execution.node_outputs or {})
        outputs[node_id] = output
        execution.node_outputs = outputs
        db.flush()
        return execution

    @staticmethod
    def requeue_due_retries(
        db: Session, campaign_id, now: datetime
    ) -> int:
        """Bulk-flip due scheduled retries back to ``queued``.

        Returns the number of rows updated.  The caller is responsible for
        committing if the count is non-zero.
        """
        workflow_ids = WorkflowRepository.ids_subquery(campaign_id)
        stmt = (
            update(Execution)
            .where(
                Execution.workflow_id.in_(workflow_ids),
                Execution.retry_status == RETRY_STATUS_SCHEDULED,
                Execution.next_retry_at.is_not(None),
                Execution.next_retry_at <= now,
            )
            .values(
                status=_EXEC_QUEUED,
                retry_status=RETRY_STATUS_PENDING,
                next_retry_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        return int(db.execute(stmt).rowcount or 0)

    # ------------------------------------------------------------------ #
    # Single-row reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def get(db: Session, execution_id: uuid.UUID) -> Execution | None:
        """Fetch an execution by primary key (no tenant check)."""
        return db.execute(
            select(Execution).where(Execution.id == execution_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_for_org(
        db: Session, org_id: uuid.UUID, execution_id: uuid.UUID
    ) -> Execution | None:
        """Tenant-scoped execution fetch (joins through workflow → campaign)."""
        return db.execute(
            select(Execution)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .join(Campaign, Campaign.id == Workflow.campaign_id)
            .where(
                Execution.id == execution_id,
                Campaign.organization_id == org_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def get_next_queued(
        db: Session, workflow_id: uuid.UUID
    ) -> Execution | None:
        """Return the oldest queued execution for a workflow (FIFO order)."""
        return db.execute(
            select(Execution)
            .where(
                Execution.workflow_id == workflow_id,
                Execution.status == _EXEC_QUEUED,
            )
            .order_by(Execution.created_at.asc())
        ).scalars().first()

    # ------------------------------------------------------------------ #
    # Collection reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_by_workflow(
        db: Session, workflow_id: uuid.UUID
    ) -> list[Execution]:
        """All executions for a workflow, oldest first."""
        return list(
            db.execute(
                select(Execution)
                .where(Execution.workflow_id == workflow_id)
                .order_by(Execution.created_at.asc())
            ).scalars()
        )

    @staticmethod
    def list_for_campaign_with_leads(
        db: Session, campaign_id: uuid.UUID, limit: int = 200
    ) -> list[tuple]:
        """Return (Execution, Lead|None) pairs for a campaign, newest-first.

        Used by the monitor endpoint to avoid N+1 lead queries.
        """
        return list(
            db.execute(
                select(Execution, Lead)
                .join(Workflow, Workflow.id == Execution.workflow_id)
                .outerjoin(Lead, Lead.id == Execution.lead_id)
                .where(Workflow.campaign_id == campaign_id)
                .order_by(Execution.updated_at.desc())
                .limit(limit)
            ).all()
        )

    @staticmethod
    def list_queued(
        db: Session,
        workflow_id: uuid.UUID,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[Execution]:
        """Up to ``limit`` dispatchable queued executions in FIFO order.

        WAIT-parked executions have ``status="queued"`` but carry a future
        ``next_retry_at`` timestamp.  They are excluded from dispatch until
        that time has passed — making this the single gate that turns a
        WAIT expiry into a live dispatch without a separate requeue step.

        Passing ``now`` explicitly (required in the scheduler tick so a
        consistent clock is used throughout the entire tick) avoids
        per-row ``datetime.now()`` drift.
        """
        now = now or datetime.now(timezone.utc)
        return list(
            db.execute(
                select(Execution)
                .where(
                    Execution.workflow_id == workflow_id,
                    Execution.status == _EXEC_QUEUED,
                    or_(
                        Execution.next_retry_at.is_(None),
                        Execution.next_retry_at <= now,
                    ),
                )
                .order_by(Execution.created_at.asc())
                .limit(limit)
            ).scalars()
        )

    @staticmethod
    def list_running(
        db: Session, workflow_id: uuid.UUID
    ) -> list[Execution]:
        """All currently running executions for a workflow."""
        return list(
            db.execute(
                select(Execution)
                .where(
                    Execution.workflow_id == workflow_id,
                    Execution.status == _EXEC_RUNNING,
                )
            ).scalars()
        )

    # ------------------------------------------------------------------ #
    # Aggregate / count queries (scoped to campaign via workflow join)
    # ------------------------------------------------------------------ #

    @staticmethod
    def count_by_status(
        db: Session, campaign_id
    ) -> dict[str, int]:
        """Return ``{status: count}`` for all executions in a campaign."""
        rows = db.execute(
            select(Execution.status, func.count())
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .where(Workflow.campaign_id == campaign_id)
            .group_by(Execution.status)
        ).all()
        return {status: int(count) for status, count in rows}

    @staticmethod
    def count_dispatched_since(
        db: Session, campaign_id, since: datetime
    ) -> int:
        """Count executions that left ``queued`` status at or after ``since``.

        Used by the pacing engine to compute how many calls have been
        dispatched in the last hour.
        """
        return int(
            db.execute(
                select(func.count())
                .select_from(Execution)
                .join(Workflow, Workflow.id == Execution.workflow_id)
                .where(
                    Workflow.campaign_id == campaign_id,
                    Execution.status != _EXEC_QUEUED,
                    Execution.updated_at >= since,
                )
            ).scalar_one()
        )

    @staticmethod
    def count_scheduled_retries(db: Session, campaign_id) -> int:
        """Count executions parked waiting for a future retry backoff."""
        return int(
            db.execute(
                select(func.count())
                .select_from(Execution)
                .join(Workflow, Workflow.id == Execution.workflow_id)
                .where(
                    Workflow.campaign_id == campaign_id,
                    Execution.retry_status == RETRY_STATUS_SCHEDULED,
                )
            ).scalar_one()
        )

    @staticmethod
    def retry_stats(db: Session, campaign_id) -> dict:
        """Aggregate retry counters for a campaign in a single query.

        Returns the same dict shape previously computed inline in
        ``CampaignScheduler._retry_stats``.
        """
        retried = case((Execution.attempt_number > 1, 1), else_=0)
        scheduled = case(
            (Execution.retry_status == RETRY_STATUS_SCHEDULED, 1), else_=0
        )
        exhausted = case(
            (Execution.retry_status == RETRY_STATUS_EXHAUSTED, 1), else_=0
        )
        succeeded = case(
            (
                (Execution.retry_status == RETRY_STATUS_COMPLETED)
                & (Execution.attempt_number > 1),
                1,
            ),
            else_=0,
        )

        row = db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Execution.attempt_number), 0),
                func.coalesce(func.sum(retried), 0),
                func.coalesce(func.sum(scheduled), 0),
                func.coalesce(func.sum(exhausted), 0),
                func.coalesce(func.sum(succeeded), 0),
            )
            .select_from(Execution)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .where(Workflow.campaign_id == campaign_id)
        ).one()

        total, sum_attempts, retried_n, pending_n, exhausted_n, success_n = (
            int(row[0]),
            int(row[1]),
            int(row[2]),
            int(row[3]),
            int(row[4]),
            int(row[5]),
        )

        total_retries = max(0, sum_attempts - total)
        avg_attempts = round(sum_attempts / total, 2) if total else 0.0
        terminal_retried = success_n + exhausted_n
        success_rate = (
            round(success_n / terminal_retried, 3)
            if terminal_retried
            else 0.0
        )

        return {
            "total_executions": total,
            "retried_executions": retried_n,
            "total_retries": total_retries,
            "pending_retries": pending_n,
            "exhausted_retries": exhausted_n,
            "successful_retries": success_n,
            "retry_success_rate": success_rate,
            "average_attempts_per_call": avg_attempts,
        }

    @staticmethod
    def count_by_node(
        db: Session, workflow_id: uuid.UUID, node_id: str
    ) -> dict[str, int]:
        """Return ``{status: count}`` for executions at a specific graph node.

        Prepared for Phase 2C graph-aware dispatch.  ``node_id`` matches
        ``Execution.current_node_id``.
        """
        rows = db.execute(
            select(Execution.status, func.count())
            .where(
                Execution.workflow_id == workflow_id,
                Execution.current_node_id == node_id,
            )
            .group_by(Execution.status)
        ).all()
        return {status: int(count) for status, count in rows}
