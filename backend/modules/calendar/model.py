"""SQLAlchemy model for storing org-level Google Calendar integrations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import BaseModel


class CalendarIntegration(BaseModel):
    """One Google Calendar OAuth connection per organisation.

    Tokens are stored encrypted (Fernet) — see :mod:`modules.calendar.encryption`.
    ``calendar_id`` defaults to ``"primary"`` which points to the connected
    account's main calendar.
    """

    __tablename__ = "calendar_integrations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="google",
    )

    # The Google account email that was authorised (display only).
    calendar_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Fernet-encrypted OAuth tokens.
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)

    # When the access token expires (UTC). We proactively refresh 5 min early.
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Which calendar to read/write. "primary" = the account's default calendar.
    calendar_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="primary",
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "provider", name="uq_calendar_integrations_org_provider"
        ),
    )
