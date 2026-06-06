"""Phase 2A — add graph columns to workflows + executions

Revision ID: p1q2r3s4t5u6
Revises: o1p2q3r4s5t6
Create Date: 2026-06-06

Changes
-------
workflows:
  * nodes     JSONB NOT NULL DEFAULT '[]' — node list for graph-based workflows
  * edges     JSONB NOT NULL DEFAULT '[]' — edge list for graph-based workflows

executions:
  * current_node_id  VARCHAR(64) NULL — which node in the graph this execution
                     is currently at; NULL means legacy flat execution
  * node_outputs     JSONB NULL DEFAULT '{}' — per-node output accumulator for
                     multi-step traversal

Constraints:
  * uq_workflows_campaign_active — partial unique index on workflows(campaign_id)
    WHERE state = 'active'.  Enforces at most one active workflow per campaign
    at the DB level, closing the race condition in CampaignService.activate.

Backward compatibility
----------------------
All new columns are either NOT NULL with a server-default (workflows) or
nullable (executions).  Existing rows will have nodes=[], edges=[] and
current_node_id=NULL, node_outputs=NULL respectively.  All existing code
paths remain valid:
  * scheduler treats current_node_id=NULL as "legacy flat execution".
  * worker treats nodes=[] as "no graph; use legacy dial/LLM path".
  * retry engine does not touch current_node_id — retries preserve the value.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p1q2r3s4t5u6"
down_revision: Union[str, Sequence[str], None] = "o1p2q3r4s5t6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Workflow graph definition columns
    # ------------------------------------------------------------------
    op.add_column(
        "workflows",
        sa.Column(
            "nodes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "workflows",
        sa.Column(
            "edges",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )

    # ------------------------------------------------------------------
    # 2. Execution node-tracking columns
    # ------------------------------------------------------------------
    op.add_column(
        "executions",
        sa.Column(
            "current_node_id",
            sa.String(64),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_executions_current_node_id",
        "executions",
        ["current_node_id"],
    )
    op.add_column(
        "executions",
        sa.Column(
            "node_outputs",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'{}'"),
        ),
    )

    # ------------------------------------------------------------------
    # 3. Partial unique index: at most one active workflow per campaign
    # ------------------------------------------------------------------
    op.create_index(
        "uq_workflows_campaign_active",
        "workflows",
        ["campaign_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_workflows_campaign_active", table_name="workflows")
    op.drop_column("executions", "node_outputs")
    op.drop_index("ix_executions_current_node_id", table_name="executions")
    op.drop_column("executions", "current_node_id")
    op.drop_column("workflows", "edges")
    op.drop_column("workflows", "nodes")
