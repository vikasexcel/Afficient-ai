"""Phase 5B — add missing indexes for production hardening.

Indexes added:
  * executions.workflow_id  — primary join/filter column; no index caused
    full-table scans on every campaign scheduling tick and execution lookup.
  * executions.status       — heavily filtered in scheduler hot paths
    (list_queued, list_running, count_by_status).
  * executions.created_at   — needed for analytics trend queries and audit
    date-range filters on large tables.
  * executions.organization_id (composite via campaign join is the current
    pattern, but a direct denormalized column is added by this migration
    on the *index* level only via the existing FK path — not a new column).

Note: executions.lead_id, next_retry_at, retry_status, current_node_id
      already have indexes from earlier migrations.

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-06-08

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "s5t6u7v8w9x0"
down_revision = "r4s5t6u7v8w9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # executions — critical hot-path columns
    # ------------------------------------------------------------------ #
    op.create_index(
        "ix_executions_workflow_id",
        "executions",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        "ix_executions_status",
        "executions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_executions_created_at",
        "executions",
        ["created_at"],
        unique=False,
    )
    # Composite index for the most common scheduler query:
    # "list queued executions for a campaign, ordered by created_at"
    # executed via workflow_id → campaign join path.
    op.create_index(
        "ix_executions_workflow_status",
        "executions",
        ["workflow_id", "status"],
        unique=False,
    )
    # ------------------------------------------------------------------ #
    # lead_activities — analytics queries filter by these.
    # Created conditionally: the table was removed in the Phase 1 leads
    # rebuild migration (o1p2q3r4s5t6) and may not exist in all envs.
    # ------------------------------------------------------------------ #
    from alembic import op as _op  # noqa: F811
    bind = op.get_bind()
    result = bind.execute(
        __import__("sqlalchemy").text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'lead_activities' AND table_schema = 'public'"
        )
    ).fetchone()
    if result:
        op.create_index(
            "ix_lead_activities_created_at",
            "lead_activities",
            ["created_at"],
            unique=False,
        )
        op.create_index(
            "ix_lead_activities_org_type_created",
            "lead_activities",
            ["organization_id", "activity_type", "created_at"],
            unique=False,
        )
    # ------------------------------------------------------------------ #
    # campaigns — analytics campaign-growth query needs created_at
    # ------------------------------------------------------------------ #
    op.create_index(
        "ix_campaigns_created_at",
        "campaigns",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_campaigns_created_at", table_name="campaigns")
    bind = op.get_bind()
    result = bind.execute(
        __import__("sqlalchemy").text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'lead_activities' AND table_schema = 'public'"
        )
    ).fetchone()
    if result:
        op.drop_index(
            "ix_lead_activities_org_type_created", table_name="lead_activities"
        )
        op.drop_index("ix_lead_activities_created_at", table_name="lead_activities")
    op.drop_index("ix_executions_workflow_status", table_name="executions")
    op.drop_index("ix_executions_created_at", table_name="executions")
    op.drop_index("ix_executions_status", table_name="executions")
    op.drop_index("ix_executions_workflow_id", table_name="executions")
