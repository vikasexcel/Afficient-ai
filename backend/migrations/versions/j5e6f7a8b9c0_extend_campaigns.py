"""extend campaigns with config fields

Revision ID: j5e6f7a8b9c0
Revises: i4d5e6f7a8b9
Create Date: 2026-06-04

Adds the campaign-configuration columns the frontend already collects but
the backend previously dropped: ``lead_list_id``, ``scheduled_at``,
``timezone``, ``business_hours`` and ``retry_config``. ``playbook_id`` and
``status`` already exist (created in earlier migrations) so they are left
untouched here.

Also extends ``executions`` with ``lead_id`` + ``context`` so a campaign can
enqueue one execution per lead and track per-lead status/output.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "j5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "i4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("lead_list_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("business_hours", sa.JSON(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("retry_config", sa.JSON(), nullable=True),
    )

    op.create_foreign_key(
        "fk_campaigns_lead_list_id",
        "campaigns",
        "lead_lists",
        ["lead_list_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_campaigns_lead_list_id"),
        "campaigns",
        ["lead_list_id"],
    )
    op.create_index(
        op.f("ix_campaigns_status"),
        "campaigns",
        ["status"],
    )
    op.create_index(
        op.f("ix_campaigns_organization_id"),
        "campaigns",
        ["organization_id"],
    )

    # Per-lead execution tracking ------------------------------------------
    op.add_column(
        "executions",
        sa.Column("lead_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column("context", sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        "fk_executions_lead_id",
        "executions",
        "leads",
        ["lead_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_executions_lead_id"), "executions", ["lead_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_executions_lead_id"), table_name="executions")
    op.drop_constraint(
        "fk_executions_lead_id", "executions", type_="foreignkey"
    )
    op.drop_column("executions", "context")
    op.drop_column("executions", "lead_id")

    op.drop_index(op.f("ix_campaigns_organization_id"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_status"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_lead_list_id"), table_name="campaigns")
    op.drop_constraint(
        "fk_campaigns_lead_list_id", "campaigns", type_="foreignkey"
    )
    op.drop_column("campaigns", "retry_config")
    op.drop_column("campaigns", "business_hours")
    op.drop_column("campaigns", "timezone")
    op.drop_column("campaigns", "scheduled_at")
    op.drop_column("campaigns", "lead_list_id")
