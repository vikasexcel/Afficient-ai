"""add_playbook_objections

Revision ID: i4d5e6f7a8b9
Revises: h3c4d5e6f7a8
Create Date: 2026-06-03 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "h3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "playbooks",
        sa.Column("objections", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("playbooks", "objections")
