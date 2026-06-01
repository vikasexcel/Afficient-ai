"""create leads + lead_lists tables

Revision ID: a1b2c3d4e5f6
Revises: f9a2c1d4e7b6
Create Date: 2026-06-01

Introduces the org-scoped ``lead_lists`` and ``leads`` tables used by the
Lead Upload module. ``leads.phone_normalized`` carries a digits-only
version of the phone so dedupe is cheap and the unique constraint can
hold even when users format numbers inconsistently.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f9a2c1d4e7b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_lists",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column(
            "lead_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_lead_lists_org_name"
        ),
    )
    op.create_index(
        op.f("ix_lead_lists_organization_id"),
        "lead_lists",
        ["organization_id"],
    )

    op.create_table(
        "leads",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("lead_list_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("phone_normalized", sa.String(length=32), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="new",
        ),
        sa.Column("tags", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["lead_list_id"], ["lead_lists.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "phone_normalized",
            name="uq_leads_org_phone",
        ),
    )
    op.create_index(
        op.f("ix_leads_organization_id"), "leads", ["organization_id"]
    )
    op.create_index(
        op.f("ix_leads_lead_list_id"), "leads", ["lead_list_id"]
    )
    op.create_index(
        op.f("ix_leads_phone_normalized"),
        "leads",
        ["phone_normalized"],
    )
    op.create_index(op.f("ix_leads_status"), "leads", ["status"])
    op.create_index(
        "ix_leads_org_created", "leads", ["organization_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_leads_org_created", table_name="leads")
    op.drop_index(op.f("ix_leads_status"), table_name="leads")
    op.drop_index(op.f("ix_leads_phone_normalized"), table_name="leads")
    op.drop_index(op.f("ix_leads_lead_list_id"), table_name="leads")
    op.drop_index(op.f("ix_leads_organization_id"), table_name="leads")
    op.drop_table("leads")

    op.drop_index(op.f("ix_lead_lists_organization_id"), table_name="lead_lists")
    op.drop_table("lead_lists")
