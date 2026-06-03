"""add_playbook_agent_name

Revision ID: h3c4d5e6f7a8
Revises: g2b3c4d5e6f7
Create Date: 2026-06-03 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "g2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "playbooks",
        sa.Column("agent_name", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("playbooks", "agent_name")
