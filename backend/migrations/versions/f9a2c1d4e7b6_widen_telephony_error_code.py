"""widen telephony_calls.error_code to varchar(64)

Revision ID: f9a2c1d4e7b6
Revises: e8f1a2b3c4d5
Create Date: 2026-06-01

The previous size (16) couldn't hold our internal failure codes such as
``twilio_originate_failed`` (23 chars), so any failed origination crashed
the request handler with StringDataRightTruncation. Widen to 64.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "f9a2c1d4e7b6"
down_revision = "e8f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "telephony_calls",
        "error_code",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "telephony_calls",
        "error_code",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=True,
    )
