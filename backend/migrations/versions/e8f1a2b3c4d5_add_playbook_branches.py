"""add_playbook_branches

Revision ID: e8f1a2b3c4d5
Revises: d4e2b91f8c03
Create Date: 2026-05-30 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d4e2b91f8c03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("playbooks", sa.Column("branches", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("playbooks", "branches")
