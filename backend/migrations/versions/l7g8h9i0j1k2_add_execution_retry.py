"""add execution retry columns

Revision ID: l7g8h9i0j1k2
Revises: k6f7a8b9c0d1
Create Date: 2026-06-04

Adds the per-execution bookkeeping consumed by the Retry Execution Engine:

* ``attempt_number``      — 1-based dial attempt counter (default 1)
* ``outcome``             — classified call outcome (no_answer, busy, ...)
* ``next_retry_at``       — when the scheduler should requeue the execution
* ``last_failure_reason`` — diagnostic text for the latest failure
* ``retry_status``        — pending | scheduled | exhausted | completed

``attempt_number`` and ``retry_status`` carry server defaults so existing
rows backfill cleanly (one completed/queued attempt, no retries pending).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "l7g8h9i0j1k2"
down_revision: Union[str, Sequence[str], None] = "k6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "executions",
        sa.Column(
            "attempt_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "executions",
        sa.Column("outcome", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column("last_failure_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column(
            "retry_status",
            sa.String(length=20),
            nullable=True,
            server_default="pending",
        ),
    )
    op.create_index(
        "ix_executions_next_retry_at",
        "executions",
        ["next_retry_at"],
    )
    op.create_index(
        "ix_executions_retry_status",
        "executions",
        ["retry_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_executions_retry_status", table_name="executions")
    op.drop_index("ix_executions_next_retry_at", table_name="executions")
    op.drop_column("executions", "retry_status")
    op.drop_column("executions", "last_failure_reason")
    op.drop_column("executions", "next_retry_at")
    op.drop_column("executions", "outcome")
    op.drop_column("executions", "attempt_number")
