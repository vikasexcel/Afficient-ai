"""add_playbook_company_fields

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-03 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "playbooks",
        sa.Column("company_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "playbooks",
        sa.Column("company_intro", sa.Text(), nullable=True),
    )
    op.add_column(
        "playbooks",
        sa.Column("company_description", sa.Text(), nullable=True),
    )
    op.add_column(
        "playbooks",
        sa.Column("value_proposition", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("playbooks", "value_proposition")
    op.drop_column("playbooks", "company_description")
    op.drop_column("playbooks", "company_intro")
    op.drop_column("playbooks", "company_name")
