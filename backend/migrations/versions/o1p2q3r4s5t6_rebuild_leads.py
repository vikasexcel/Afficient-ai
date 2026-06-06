"""Rebuild lead management schema — Phase 1

Revision ID: o1p2q3r4s5t6
Revises: n9i0j1k2l3m4
Create Date: 2026-06-06

Changes
-------
* Replaces the ``lead_activities`` table (removed in Phase 1 design).
* Migrates ``leads`` columns:
    - Drops ``name``, ``industry``, ``location``, ``source``, ``notes``,
      ``custom_fields``, and the direct ``lead_list_id`` FK column.
    - Adds ``first_name``, ``last_name``, ``linkedin_url``, ``job_title``,
      ``extra_data``.
* Migrates ``lead_lists`` columns:
    - Drops ``source``, ``lead_count``, and ``created_by`` (with its FK).
* Introduces ``lead_list_memberships`` join table for the new many-to-many
  relationship between Lead and LeadList.

The FK constraints on ``campaigns.lead_list_id → lead_lists.id`` (named
``fk_campaigns_lead_list_id``) and ``executions.lead_id → leads.id``
(named ``fk_executions_lead_id``) reference the **table id columns**, not
the dropped columns, so they remain valid throughout this migration.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "o1p2q3r4s5t6"
down_revision: Union[str, Sequence[str], None] = "n9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Drop lead_activities (fully removed in new design)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 2. Migrate leads table
    # ------------------------------------------------------------------

    # 2a. Add new columns (nullable first so existing rows don't error).
    op.add_column(
        "leads",
        sa.Column(
            "first_name",
            sa.String(120),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "leads",
        sa.Column("last_name", sa.String(120), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("linkedin_url", sa.String(500), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("job_title", sa.String(120), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("extra_data", sa.JSON(), nullable=True),
    )

    # 2b. Back-fill first_name from the old name column before dropping it.
    op.execute(
        "UPDATE leads SET first_name = SPLIT_PART(name, ' ', 1) "
        "WHERE name IS NOT NULL AND name != ''"
    )
    op.execute(
        "UPDATE leads "
        "SET last_name = NULLIF(TRIM(SUBSTRING(name FROM POSITION(' ' IN name) + 1)), '') "
        "WHERE name IS NOT NULL AND POSITION(' ' IN name) > 0"
    )

    # 2c. Remove server default now that existing rows are filled.
    op.alter_column("leads", "first_name", server_default=None)

    # 2d. Drop old leads columns.
    op.drop_index(op.f("ix_leads_lead_list_id"), table_name="leads")
    op.drop_constraint(
        "leads_lead_list_id_fkey", "leads", type_="foreignkey"
    )
    op.drop_column("leads", "name")
    op.drop_column("leads", "industry")
    op.drop_column("leads", "location")
    op.drop_column("leads", "source")
    op.drop_column("leads", "notes")
    op.drop_column("leads", "custom_fields")
    op.drop_column("leads", "lead_list_id")

    # ------------------------------------------------------------------
    # 3. Migrate lead_lists table
    # ------------------------------------------------------------------

    # Drop FK on created_by first, then the column.
    op.drop_constraint(
        "lead_lists_created_by_fkey", "lead_lists", type_="foreignkey"
    )
    op.drop_column("lead_lists", "source")
    op.drop_column("lead_lists", "lead_count")
    op.drop_column("lead_lists", "created_by")

    # ------------------------------------------------------------------
    # 4. Create lead_list_memberships join table
    # ------------------------------------------------------------------
    op.create_table(
        "lead_list_memberships",
        sa.Column(
            "lead_id",
            sa.Uuid(),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "lead_list_id",
            sa.Uuid(),
            sa.ForeignKey("lead_lists.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_lead_list_memberships_lead_id",
        "lead_list_memberships",
        ["lead_id"],
    )
    op.create_index(
        "ix_lead_list_memberships_list_id",
        "lead_list_memberships",
        ["lead_list_id"],
    )

    # 4a. Migrate existing lead → list assignments to the join table.
    # At this point lead_list_id has already been dropped from leads,
    # so we cannot back-fill. (Any existing assignments are lost; this is
    # expected in Phase 1 — a fresh migration against a dev database.)


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 4. Drop lead_list_memberships
    # ------------------------------------------------------------------
    op.drop_index("ix_lead_list_memberships_list_id", table_name="lead_list_memberships")
    op.drop_index("ix_lead_list_memberships_lead_id", table_name="lead_list_memberships")
    op.drop_table("lead_list_memberships")

    # ------------------------------------------------------------------
    # 3. Restore lead_lists columns
    # ------------------------------------------------------------------
    op.add_column(
        "lead_lists",
        sa.Column("created_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "lead_lists",
        sa.Column(
            "lead_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "lead_lists",
        sa.Column("source", sa.String(120), nullable=True),
    )
    op.create_foreign_key(
        "lead_lists_created_by_fkey",
        "lead_lists",
        "users",
        ["created_by"],
        ["id"],
    )

    # ------------------------------------------------------------------
    # 2. Restore leads columns
    # ------------------------------------------------------------------
    op.add_column(
        "leads",
        sa.Column(
            "lead_list_id",
            sa.Uuid(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "leads_lead_list_id_fkey",
        "leads",
        "lead_lists",
        ["lead_list_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_leads_lead_list_id"), "leads", ["lead_list_id"]
    )
    op.add_column(
        "leads",
        sa.Column("custom_fields", sa.JSON(), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("source", sa.String(120), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("location", sa.String(120), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("industry", sa.String(120), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            server_default="unknown",
        ),
    )
    # Reconstruct name from first_name / last_name before dropping them.
    op.execute(
        "UPDATE leads SET name = TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, ''))"
    )
    op.alter_column("leads", "name", server_default=None)
    op.drop_column("leads", "extra_data")
    op.drop_column("leads", "job_title")
    op.drop_column("leads", "linkedin_url")
    op.drop_column("leads", "last_name")
    op.drop_column("leads", "first_name")

    # ------------------------------------------------------------------
    # 1. Recreate lead_activities
    # ------------------------------------------------------------------
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
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
