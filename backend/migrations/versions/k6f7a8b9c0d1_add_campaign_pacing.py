"""add campaign pacing columns

Revision ID: k6f7a8b9c0d1
Revises: j5e6f7a8b9c0
Create Date: 2026-06-04

Adds the pacing controls consumed by the automatic call-scheduling engine:
``calls_per_hour`` (rolling-hour rate cap) and ``max_concurrent_calls``
(simultaneous in-flight calls). Both are nullable: ``NULL`` falls back to the
``CAMPAIGN_DEFAULT_*`` settings and ``0`` means "unlimited".
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "k6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "j5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("calls_per_hour", sa.Integer(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("max_concurrent_calls", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "max_concurrent_calls")
    op.drop_column("campaigns", "calls_per_hour")
