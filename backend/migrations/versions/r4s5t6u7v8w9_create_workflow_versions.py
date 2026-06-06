"""Phase 3C — create workflow_versions table

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-06-06

Changes
-------
* Creates ``workflow_versions`` table with columns:
    - id              UUID PK
    - workflow_id     UUID FK → workflows.id (CASCADE DELETE)
    - version         INTEGER NOT NULL
    - nodes           JSON NOT NULL
    - edges           JSON NOT NULL
    - created_by      UUID NULL  (user who triggered the save; nullable for
                      automated / system-initiated versions)
    - created_at      TIMESTAMP NOT NULL

* Unique constraint on (workflow_id, version) — each version number appears
  at most once per workflow.
* Composite index on (workflow_id, version) for ordered version-list queries.
* No data migration needed — existing workflows start with an empty version
  history; version records are created lazily on the first graph save after
  this migration runs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "r4s5t6u7v8w9"
down_revision: str = "q3r4s5t6u7v8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_versions",
        sa.Column("id",          sa.UUID(),      nullable=False),
        sa.Column("workflow_id", sa.UUID(),      nullable=False),
        sa.Column("version",     sa.Integer(),   nullable=False),
        sa.Column("nodes",       sa.JSON(),      nullable=False,
                  server_default="[]"),
        sa.Column("edges",       sa.JSON(),      nullable=False,
                  server_default="[]"),
        sa.Column("created_by",  sa.UUID(),      nullable=True),
        sa.Column("created_at",  sa.DateTime(),  nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            ondelete="CASCADE",
            name="fk_workflow_versions_workflow_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_id", "version",
            name="uq_workflow_versions_workflow_id_version",
        ),
    )
    op.create_index(
        "ix_workflow_versions_workflow_id",
        "workflow_versions",
        ["workflow_id"],
    )
    op.create_index(
        "ix_workflow_versions_workflow_id_version",
        "workflow_versions",
        ["workflow_id", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_versions_workflow_id_version", "workflow_versions")
    op.drop_index("ix_workflow_versions_workflow_id",          "workflow_versions")
    op.drop_table("workflow_versions")
