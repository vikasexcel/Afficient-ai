"""add calendar_integrations table

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-06-11

Stores one Google Calendar OAuth connection per organisation.
Tokens are stored encrypted (Fernet) — never in plaintext.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "w9x0y1z2a3b4"
down_revision: Union[str, Sequence[str], None] = "v8w9x0y1z2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_integrations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="google"),
        sa.Column("calendar_email", sa.String(255), nullable=True),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("token_expiry", sa.DateTime(), nullable=True),
        sa.Column("calendar_id", sa.String(255), nullable=False, server_default="primary"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "provider",
            name="uq_calendar_integrations_org_provider",
        ),
    )
    op.create_index(
        "ix_calendar_integrations_org",
        "calendar_integrations",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_integrations_org", table_name="calendar_integrations")
    op.drop_table("calendar_integrations")
