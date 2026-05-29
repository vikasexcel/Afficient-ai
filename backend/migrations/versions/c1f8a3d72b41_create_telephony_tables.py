"""create_telephony_tables

Revision ID: c1f8a3d72b41
Revises: 9fc7dd0db59a
Create Date: 2026-05-29 15:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1f8a3d72b41"
down_revision: Union[str, Sequence[str], None] = "9fc7dd0db59a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "telephony_calls",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("call_sid", sa.String(length=64), nullable=True),
        sa.Column("room_name", sa.String(length=128), nullable=False),
        sa.Column(
            "direction",
            sa.String(length=16),
            nullable=False,
            server_default="outbound",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("from_number", sa.String(length=32), nullable=False),
        sa.Column("to_number", sa.String(length=32), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("lead_name", sa.String(length=255), nullable=True),
        sa.Column("lead_phone", sa.String(length=32), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("initiated_at", sa.DateTime(), nullable=True),
        sa.Column("ringing_at", sa.DateTime(), nullable=True),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("price_unit", sa.String(length=8), nullable=True),
        sa.Column("error_code", sa.String(length=16), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("parent_call_id", sa.Uuid(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["parent_call_id"], ["telephony_calls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_telephony_calls_call_sid"),
        "telephony_calls",
        ["call_sid"],
        unique=True,
    )
    op.create_index(
        op.f("ix_telephony_calls_room_name"),
        "telephony_calls",
        ["room_name"],
        unique=True,
    )
    op.create_index(
        op.f("ix_telephony_calls_organization_id"),
        "telephony_calls",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telephony_calls_status"),
        "telephony_calls",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telephony_calls_lead_id"),
        "telephony_calls",
        ["lead_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telephony_calls_campaign_id"),
        "telephony_calls",
        ["campaign_id"],
        unique=False,
    )

    op.create_table(
        "telephony_events",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("call_sid", sa.String(length=64), nullable=True),
        sa.Column("telephony_call_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="twilio",
        ),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["telephony_call_id"], ["telephony_calls.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_telephony_events_call_sid"),
        "telephony_events",
        ["call_sid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telephony_events_event_type"),
        "telephony_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telephony_events_organization_id"),
        "telephony_events",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telephony_events_telephony_call_id"),
        "telephony_events",
        ["telephony_call_id"],
        unique=False,
    )
    op.create_index(
        "ix_telephony_events_call_created",
        "telephony_events",
        ["call_sid", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(
        "ix_telephony_events_call_created", table_name="telephony_events"
    )
    op.drop_index(
        op.f("ix_telephony_events_telephony_call_id"),
        table_name="telephony_events",
    )
    op.drop_index(
        op.f("ix_telephony_events_organization_id"),
        table_name="telephony_events",
    )
    op.drop_index(
        op.f("ix_telephony_events_event_type"),
        table_name="telephony_events",
    )
    op.drop_index(
        op.f("ix_telephony_events_call_sid"),
        table_name="telephony_events",
    )
    op.drop_table("telephony_events")

    op.drop_index(
        op.f("ix_telephony_calls_campaign_id"),
        table_name="telephony_calls",
    )
    op.drop_index(
        op.f("ix_telephony_calls_lead_id"), table_name="telephony_calls"
    )
    op.drop_index(
        op.f("ix_telephony_calls_status"), table_name="telephony_calls"
    )
    op.drop_index(
        op.f("ix_telephony_calls_organization_id"),
        table_name="telephony_calls",
    )
    op.drop_index(
        op.f("ix_telephony_calls_room_name"),
        table_name="telephony_calls",
    )
    op.drop_index(
        op.f("ix_telephony_calls_call_sid"), table_name="telephony_calls"
    )
    op.drop_table("telephony_calls")
