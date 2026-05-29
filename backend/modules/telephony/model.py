"""Persistence models for the telephony module.

Two tables:

* ``telephony_calls`` — one row per Twilio call (outbound or inbound).
  Holds the canonical ``call_sid``, the LiveKit ``room_name`` (also the
  AI ``call_id`` — 1:1 with the orchestrator), call status, timing,
  optional lead/campaign associations, and Twilio cost metadata.
* ``telephony_events`` — append-only audit log of every Twilio webhook
  callback (``initiated``, ``ringing``, ``answered``, ``completed``,
  ``failed``, ``busy``, ``no-answer``). Stores the raw form payload as
  JSON so we can re-derive state without re-asking Twilio.

The ``room_name`` and ``call_id`` are the same string by design so a
single grep across the LiveKit / STT / TTS / AI / telephony logs traces
the full lifecycle of one phone call.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import BaseModel


# Status values stored in ``telephony_calls.status``. Aligns 1:1 with
# Twilio's CallStatus vocabulary plus a couple of internal states.
CALL_STATUS_QUEUED = "queued"
CALL_STATUS_INITIATED = "initiated"
CALL_STATUS_RINGING = "ringing"
CALL_STATUS_IN_PROGRESS = "in-progress"
CALL_STATUS_COMPLETED = "completed"
CALL_STATUS_FAILED = "failed"
CALL_STATUS_BUSY = "busy"
CALL_STATUS_NO_ANSWER = "no-answer"
CALL_STATUS_CANCELED = "canceled"

TERMINAL_STATUSES = frozenset(
    {
        CALL_STATUS_COMPLETED,
        CALL_STATUS_FAILED,
        CALL_STATUS_BUSY,
        CALL_STATUS_NO_ANSWER,
        CALL_STATUS_CANCELED,
    }
)


class TelephonyCall(BaseModel):
    """One Twilio call. Also the join row between Twilio and LiveKit."""

    __tablename__ = "telephony_calls"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    # Twilio CallSid (e.g. CAxxxxx...). Nullable until the REST call
    # returns — there is a brief window between row insert and Twilio
    # accepting the request where we hold the row without a SID.
    call_sid: Mapped[str | None] = mapped_column(
        String(64), index=True, unique=True, nullable=True
    )

    # LiveKit room (= AI call_id). Generated server-side per call.
    room_name: Mapped[str] = mapped_column(
        String(128), index=True, unique=True
    )

    direction: Mapped[str] = mapped_column(
        String(16), default="outbound"
    )
    status: Mapped[str] = mapped_column(
        String(32), default=CALL_STATUS_QUEUED, index=True
    )

    from_number: Mapped[str] = mapped_column(String(32))
    to_number: Mapped[str] = mapped_column(String(32))

    # Loose lead/campaign linkage. ``lead_id`` is intentionally nullable
    # without a FK constraint because a Leads table is not yet part of
    # the schema; CRM imports populate it once leads land in PG.
    lead_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    lead_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id"),
        nullable=True,
        index=True,
    )

    # Timing
    queued_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    initiated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    ringing_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # Twilio cost (e.g. price=-0.0085 unit="USD") — populated from the
    # completed webhook if available.
    price: Mapped[float | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    price_unit: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )

    # Failure / retry bookkeeping
    error_code: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    parent_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("telephony_calls.id"),
        nullable=True,
    )

    # Free-form bag — used for opening_line, persona, extra_context,
    # answer-machine detection results, etc. Persisted as JSON so the
    # row stays append-friendly without a schema bump.
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TelephonyEvent(BaseModel):
    """Append-only log of Twilio status callbacks (or local state changes).

    One row per webhook delivery. We keep the raw form payload so we can
    re-derive state or hand it to a debugging engineer without re-asking
    the Twilio API.
    """

    __tablename__ = "telephony_events"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )

    # The CallSid the webhook was about. Indexed (non-unique) for fast
    # "give me all events for this call" lookups.
    call_sid: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    # Local row id for fast joins back to the call.
    telephony_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("telephony_calls.id"),
        nullable=True,
        index=True,
    )

    # ``initiated``, ``ringing``, ``answered``, ``in-progress``,
    # ``completed``, ``failed``, ``busy``, ``no-answer``, ``canceled``,
    # or internal markers like ``ai_agent_started`` / ``ai_agent_stopped``.
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    source: Mapped[str] = mapped_column(String(32), default="twilio")

    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# Speed up "give me all events for this call, in order" — primary
# webhook reconstruction query.
Index(
    "ix_telephony_events_call_created",
    TelephonyEvent.call_sid,
    TelephonyEvent.created_at,
)
