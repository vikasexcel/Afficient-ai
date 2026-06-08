"""Add display_name to leads.

Adds an optional ``display_name`` column (VARCHAR 255, nullable) to the
``leads`` table.  When set, the UI and calling subsystem use it as the
primary label for the lead; when NULL the frontend falls back to
``first_name || ' ' || last_name``.

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-06-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision = "t6u7v8w9x0y1"
down_revision = "s5t6u7v8w9x0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("display_name", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "display_name")
