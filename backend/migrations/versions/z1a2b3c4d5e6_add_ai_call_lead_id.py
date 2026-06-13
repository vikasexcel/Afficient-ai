"""add_ai_call_lead_id

Adds a nullable ``lead_id`` foreign key to ``ai_calls`` so call transcripts
can be linked to CRM lead records.

Revision ID: z1a2b3c4d5e6
Revises: y2z3a4b5c6d7
Create Date: 2026-06-13 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "y2z3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_calls",
        sa.Column("lead_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ai_calls_lead_id",
        "ai_calls",
        "leads",
        ["lead_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_ai_calls_lead_id"),
        "ai_calls",
        ["lead_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_calls_lead_id"), table_name="ai_calls")
    op.drop_constraint("fk_ai_calls_lead_id", "ai_calls", type_="foreignkey")
    op.drop_column("ai_calls", "lead_id")
