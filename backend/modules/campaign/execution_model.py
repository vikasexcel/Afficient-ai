import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import BaseModel


class Execution(BaseModel):
    __tablename__ = "executions"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id")
    )
    status: Mapped[str] = mapped_column(String(50), default="queued")
    output: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional link to the lead this execution dials, plus a frozen context
    # snapshot (lead + playbook info) captured at enqueue time so the worker
    # can run without re-querying and so analytics stay correct after edits.
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ----------------------------------------------------------------- #
    # Retry-engine bookkeeping (driven by the campaign ``retry_config``).
    # A single execution row is retried *in place*: each failed call
    # increments ``attempt_number`` and sets ``next_retry_at`` so the
    # scheduler can requeue it once that time arrives.
    # ----------------------------------------------------------------- #

    # 1-based attempt counter; the upcoming/most-recent dial attempt.
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )

    # Classified call outcome (e.g. no_answer, busy, qualified, ...). Drives
    # the retryable decision; distinct from the lifecycle ``status`` column.
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # When the scheduler should requeue this execution for another attempt.
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        index=True,
    )

    # Human-readable reason for the most recent failure (for diagnostics).
    last_failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Retry lifecycle: pending | scheduled | exhausted | completed.
    retry_status: Mapped[str | None] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=True,
        index=True,
    )

    # ----------------------------------------------------------------- #
    # Graph-aware execution tracking (Phase 2A).
    # NULL values indicate a legacy flat execution — all existing scheduler
    # and worker code paths treat NULL as "use legacy linear behaviour".
    # ----------------------------------------------------------------- #

    # Which node in the workflow graph this execution is currently at.
    # NULL for legacy executions that predate node-based workflows.
    current_node_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    # Accumulated per-node outputs for multi-step graph traversal.
    # Keyed by node id; NULL until the first node completes.
    node_outputs: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
