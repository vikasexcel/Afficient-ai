"""add_playbook_voice_config

Adds per-playbook voice configuration columns. ``voice_id`` already exists
(created in d4e2b91f8c03); this revision adds the surrounding metadata so the
UI can offer human-readable voice selection and so multiple TTS providers can
be supported in future.

Revision ID: f1a2b3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-03 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "playbooks",
        sa.Column("voice_provider", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "playbooks",
        sa.Column("voice_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "playbooks",
        sa.Column("voice_gender", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "playbooks",
        sa.Column("voice_accent", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "playbooks",
        sa.Column("voice_language", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("playbooks", "voice_language")
    op.drop_column("playbooks", "voice_accent")
    op.drop_column("playbooks", "voice_gender")
    op.drop_column("playbooks", "voice_name")
    op.drop_column("playbooks", "voice_provider")
