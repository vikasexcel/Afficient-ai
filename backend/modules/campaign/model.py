import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from database.base import BaseModel


# Status vocabulary kept as plain strings (Alembic-friendly + greppable).
CAMPAIGN_STATUS_DRAFT = "draft"
CAMPAIGN_STATUS_SCHEDULED = "scheduled"
CAMPAIGN_STATUS_ACTIVE = "active"
CAMPAIGN_STATUS_PAUSED = "paused"
CAMPAIGN_STATUS_COMPLETED = "completed"
CAMPAIGN_STATUS_ARCHIVED = "archived"

ALL_CAMPAIGN_STATUSES = frozenset(
    {
        CAMPAIGN_STATUS_DRAFT,
        CAMPAIGN_STATUS_SCHEDULED,
        CAMPAIGN_STATUS_ACTIVE,
        CAMPAIGN_STATUS_PAUSED,
        CAMPAIGN_STATUS_COMPLETED,
        CAMPAIGN_STATUS_ARCHIVED,
    }
)


class Campaign(BaseModel):

    __tablename__ = "campaigns"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(
        String(50),
        default=CAMPAIGN_STATUS_DRAFT,
        index=True,
    )

    playbook_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("playbooks.id"),
        nullable=True,
        index=True,
    )

    lead_list_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lead_lists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # When the campaign should begin dialing. Null == start immediately on
    # activation. Stored in UTC; ``timezone`` carries the caller's IANA zone
    # so the UI can render the local wall-clock time back.
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    timezone: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # {"days": ["mon",...], "start": "09:00", "end": "17:00",
    #  "skip_holidays": true}
    business_hours: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # {"max_attempts": 3, "backoff_minutes": 60, "retry_on": ["no_answer"]}
    retry_config: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Answering Machine Detection (AMD) + Voicemail Drop settings.
    # {"voicemail_enabled": true, "voicemail_message_url": "https://...",
    #  "retry_on_voicemail": false, "amd_unknown_fallback": "human"}
    # ``NULL`` means voicemail handling is disabled for the campaign.
    voicemail_config: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # ----------------------------------------------------------------- #
    # Pacing controls (consumed by the call-scheduling engine).
    # ``NULL`` falls back to the ``CAMPAIGN_DEFAULT_*`` settings; ``0``
    # means "unlimited" for that specific constraint.
    # ----------------------------------------------------------------- #

    # Maximum new calls dispatched per rolling hour.
    calls_per_hour: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Maximum simultaneously in-flight (running) calls.
    max_concurrent_calls: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
