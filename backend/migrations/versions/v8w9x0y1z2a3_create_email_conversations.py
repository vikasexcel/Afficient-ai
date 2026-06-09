"""create email_conversations and email_messages tables

Revision ID: v8w9x0y1z2a3
Revises: u7v8w9x0y1z2
Create Date: 2026-06-09

Creates the two tables that back the webhook-based email conversation loop:

* ``email_conversations`` — one row per lead per campaign run, tracking
  the RFC 2822 thread (root_message_id, last_message_id, references_chain).
* ``email_messages`` — one row per individual email (sent or received).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "v8w9x0y1z2a3"
down_revision: Union[str, Sequence[str], None] = "u7v8w9x0y1z2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── email_conversations ────────────────────────────────────────────────
    op.create_table(
        "email_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("root_message_id", sa.String(512), nullable=False),
        sa.Column("last_message_id", sa.String(512), nullable=False),
        sa.Column("references_chain", sa.Text(), nullable=False, server_default=""),
        sa.Column("subject", sa.String(998), nullable=False, server_default=""),
        sa.Column("lead_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_turns", sa.Integer(), nullable=False, server_default="10"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["executions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_conversations_organization_id"),
        "email_conversations",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_email_conversations_lead_id"),
        "email_conversations",
        ["lead_id"],
    )
    op.create_index(
        op.f("ix_email_conversations_execution_id"),
        "email_conversations",
        ["execution_id"],
    )
    op.create_index(
        op.f("ix_email_conversations_campaign_id"),
        "email_conversations",
        ["campaign_id"],
    )
    op.create_index(
        "ix_email_conversations_lead_status",
        "email_conversations",
        ["lead_id", "status"],
    )
    op.create_index(
        "ix_email_conversations_root_message_id",
        "email_conversations",
        ["root_message_id"],
    )

    # ── email_messages ─────────────────────────────────────────────────────
    op.create_table(
        "email_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("message_id", sa.String(512), nullable=False),
        sa.Column("in_reply_to", sa.String(512), nullable=True),
        sa.Column("references", sa.Text(), nullable=True),
        sa.Column("subject", sa.String(998), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["email_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_messages_conversation_id"),
        "email_messages",
        ["conversation_id"],
    )
    op.create_index(
        op.f("ix_email_messages_organization_id"),
        "email_messages",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_email_messages_lead_id"),
        "email_messages",
        ["lead_id"],
    )
    op.create_index(
        "ix_email_messages_conv_sent",
        "email_messages",
        ["conversation_id", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_messages_conv_sent", table_name="email_messages")
    op.drop_index(
        op.f("ix_email_messages_lead_id"), table_name="email_messages"
    )
    op.drop_index(
        op.f("ix_email_messages_organization_id"), table_name="email_messages"
    )
    op.drop_index(
        op.f("ix_email_messages_conversation_id"), table_name="email_messages"
    )
    op.drop_table("email_messages")

    op.drop_index(
        "ix_email_conversations_root_message_id",
        table_name="email_conversations",
    )
    op.drop_index(
        "ix_email_conversations_lead_status",
        table_name="email_conversations",
    )
    op.drop_index(
        op.f("ix_email_conversations_campaign_id"),
        table_name="email_conversations",
    )
    op.drop_index(
        op.f("ix_email_conversations_execution_id"),
        table_name="email_conversations",
    )
    op.drop_index(
        op.f("ix_email_conversations_lead_id"),
        table_name="email_conversations",
    )
    op.drop_index(
        op.f("ix_email_conversations_organization_id"),
        table_name="email_conversations",
    )
    op.drop_table("email_conversations")
