"""create lead_activities table

Revision ID: m8h9i0j1k2l3
Revises: l7g8h9i0j1k2
Create Date: 2026-06-04

Adds the ``lead_activities`` table that backs the lead activity timeline
(call / email / meeting / note). Each row is org-scoped, references its
lead with ``ON DELETE CASCADE`` so deleting a lead cleans up its history,
and records the acting user plus a ``created_at`` timestamp.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "m8h9i0j1k2l3"
down_revision: Union[str, Sequence[str], None] = "l7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_activities",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("activity_type", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"]
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lead_activities_organization_id"),
        "lead_activities",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_lead_activities_lead_id"),
        "lead_activities",
        ["lead_id"],
    )
    op.create_index(
        "ix_lead_activities_lead_created",
        "lead_activities",
        ["lead_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lead_activities_lead_created", table_name="lead_activities"
    )
    op.drop_index(
        op.f("ix_lead_activities_lead_id"), table_name="lead_activities"
    )
    op.drop_index(
        op.f("ix_lead_activities_organization_id"),
        table_name="lead_activities",
    )
    op.drop_table("lead_activities")
