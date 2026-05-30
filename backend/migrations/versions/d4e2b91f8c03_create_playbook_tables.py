"""create_playbook_tables

Revision ID: d4e2b91f8c03
Revises: c1f8a3d72b41
Create Date: 2026-05-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e2b91f8c03"
down_revision: Union[str, Sequence[str], None] = "c1f8a3d72b41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "playbooks",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("framework", sa.String(length=16), nullable=False),
        sa.Column("persona_name", sa.String(length=64), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("opening_line", sa.Text(), nullable=True),
        sa.Column("default_objective", sa.String(length=255), nullable=True),
        sa.Column("voice_id", sa.String(length=64), nullable=True),
        sa.Column("default_context", sa.JSON(), nullable=True),
        sa.Column("disqualifying_patterns", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_playbooks_org_name"),
    )
    op.create_index(op.f("ix_playbooks_organization_id"), "playbooks", ["organization_id"])
    op.create_index(op.f("ix_playbooks_status"), "playbooks", ["status"])
    op.create_index("ix_playbooks_org_updated", "playbooks", ["organization_id", "updated_at"])

    op.create_table(
        "playbook_fields",
        sa.Column("playbook_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("cue_patterns", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("playbook_id", "key", name="uq_playbook_field_key"),
    )
    op.create_index(op.f("ix_playbook_fields_playbook_id"), "playbook_fields", ["playbook_id"])

    op.create_table(
        "playbook_versions",
        sa.Column("playbook_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("playbook_id", "version", name="uq_playbook_version"),
    )
    op.create_index(op.f("ix_playbook_versions_playbook_id"), "playbook_versions", ["playbook_id"])
    op.create_index(op.f("ix_playbook_versions_organization_id"), "playbook_versions", ["organization_id"])

    op.add_column("ai_calls", sa.Column("playbook_id", sa.Uuid(), nullable=True))
    op.add_column("ai_calls", sa.Column("playbook_version", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_ai_calls_playbook_id", "ai_calls", "playbooks", ["playbook_id"], ["id"]
    )
    op.create_index(op.f("ix_ai_calls_playbook_id"), "ai_calls", ["playbook_id"])

    op.add_column("telephony_calls", sa.Column("playbook_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_telephony_calls_playbook_id",
        "telephony_calls",
        "playbooks",
        ["playbook_id"],
        ["id"],
    )
    op.create_index(op.f("ix_telephony_calls_playbook_id"), "telephony_calls", ["playbook_id"])

    op.add_column("campaigns", sa.Column("playbook_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_campaigns_playbook_id", "campaigns", "playbooks", ["playbook_id"], ["id"]
    )
    op.create_index(op.f("ix_campaigns_playbook_id"), "campaigns", ["playbook_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_campaigns_playbook_id"), table_name="campaigns")
    op.drop_constraint("fk_campaigns_playbook_id", "campaigns", type_="foreignkey")
    op.drop_column("campaigns", "playbook_id")

    op.drop_index(op.f("ix_telephony_calls_playbook_id"), table_name="telephony_calls")
    op.drop_constraint("fk_telephony_calls_playbook_id", "telephony_calls", type_="foreignkey")
    op.drop_column("telephony_calls", "playbook_id")

    op.drop_index(op.f("ix_ai_calls_playbook_id"), table_name="ai_calls")
    op.drop_constraint("fk_ai_calls_playbook_id", "ai_calls", type_="foreignkey")
    op.drop_column("ai_calls", "playbook_version")
    op.drop_column("ai_calls", "playbook_id")

    op.drop_index(op.f("ix_playbook_versions_organization_id"), table_name="playbook_versions")
    op.drop_index(op.f("ix_playbook_versions_playbook_id"), table_name="playbook_versions")
    op.drop_table("playbook_versions")

    op.drop_index(op.f("ix_playbook_fields_playbook_id"), table_name="playbook_fields")
    op.drop_table("playbook_fields")

    op.drop_index("ix_playbooks_org_updated", table_name="playbooks")
    op.drop_index(op.f("ix_playbooks_status"), table_name="playbooks")
    op.drop_index(op.f("ix_playbooks_organization_id"), table_name="playbooks")
    op.drop_table("playbooks")
