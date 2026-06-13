"""add call recording columns to telephony_calls

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-06-13

Adds four columns that track the S3-stored call recording produced by
Twilio when TWILIO_CALL_RECORD=true:

  recording_sid            — Twilio RecordingSid (RExxx…)
  recording_url            — S3 object key (path within the recordings bucket)
  recording_duration_seconds — length of the recording in whole seconds
  recording_uploaded_at    — UTC timestamp when the file landed in S3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y2z3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "x1y2z3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telephony_calls",
        sa.Column("recording_sid", sa.String(64), nullable=True),
    )
    op.add_column(
        "telephony_calls",
        sa.Column("recording_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "telephony_calls",
        sa.Column("recording_duration_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "telephony_calls",
        sa.Column(
            "recording_uploaded_at",
            sa.DateTime(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_telephony_calls_recording_sid",
        "telephony_calls",
        ["recording_sid"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telephony_calls_recording_sid",
        table_name="telephony_calls",
    )
    op.drop_column("telephony_calls", "recording_uploaded_at")
    op.drop_column("telephony_calls", "recording_duration_seconds")
    op.drop_column("telephony_calls", "recording_url")
    op.drop_column("telephony_calls", "recording_sid")
