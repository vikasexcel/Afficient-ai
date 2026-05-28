"""Persistence model for LiveKit room sessions.

We keep a lightweight record per room so we can attribute usage to an
organisation/user, store metadata, and reconcile state with the LiveKit
server. The room itself lives in LiveKit; this row is the local handle.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import BaseModel


class LiveKitSession(BaseModel):
    __tablename__ = "livekit_sessions"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    room_name: Mapped[str] = mapped_column(String(128), index=True, unique=True)
    livekit_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="created")

    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
