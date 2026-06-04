"""add AMD + voicemail drop columns

Revision ID: n9i0j1k2l3m4
Revises: m8h9i0j1k2l3
Create Date: 2026-06-04

Adds Answering Machine Detection (AMD) + Voicemail Drop bookkeeping:

* ``telephony_calls`` gains the per-call detection / drop result columns:
  ``amd_result``, ``amd_confidence``, ``voicemail_detected_at``,
  ``voicemail_dropped`` (NOT NULL, default ``false``), ``voicemail_dropped_at``
  and ``voicemail_recording_url``.
* ``campaigns`` gains a ``voicemail_config`` JSON blob holding the campaign's
  voicemail settings (``voicemail_enabled`` / ``voicemail_message_url`` /
  ``retry_on_voicemail`` / ``amd_unknown_fallback``).

``voicemail_dropped`` carries a server default so existing rows backfill
cleanly to "no drop attempted".
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "n9i0j1k2l3m4"
down_revision: Union[str, Sequence[str], None] = "m8h9i0j1k2l3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telephony_calls",
        sa.Column("amd_result", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "telephony_calls",
        sa.Column("amd_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "telephony_calls",
        sa.Column("voicemail_detected_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "telephony_calls",
        sa.Column(
            "voicemail_dropped",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "telephony_calls",
        sa.Column("voicemail_dropped_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "telephony_calls",
        sa.Column("voicemail_recording_url", sa.Text(), nullable=True),
    )
    op.create_index(
        op.f("ix_telephony_calls_amd_result"),
        "telephony_calls",
        ["amd_result"],
    )

    op.add_column(
        "campaigns",
        sa.Column("voicemail_config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "voicemail_config")

    op.drop_index(
        op.f("ix_telephony_calls_amd_result"),
        table_name="telephony_calls",
    )
    op.drop_column("telephony_calls", "voicemail_recording_url")
    op.drop_column("telephony_calls", "voicemail_dropped_at")
    op.drop_column("telephony_calls", "voicemail_dropped")
    op.drop_column("telephony_calls", "voicemail_detected_at")
    op.drop_column("telephony_calls", "amd_confidence")
    op.drop_column("telephony_calls", "amd_result")
