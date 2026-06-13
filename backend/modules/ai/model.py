"""Persistence models for AI conversations.

Three tables:

* ``ai_calls`` — one row per call/session. Owns the call_id we use as the
  Redis memory key and as the LiveKit room name (1:1 in this iteration).
* ``ai_transcript_entries`` — one row per message (user/assistant/system).
  Append-only; populated on every turn for audit/replay.
* ``ai_call_summaries`` — one row per call, written at end-of-call by
  :meth:`modules.ai.service.AIService.finalize_call`. Holds the textual
  summary, qualification snapshot, and aggregate token usage.

We split summaries off from ``ai_calls`` so the audit log stays trivial
to insert per turn — no need to read-modify-write the call row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import BaseModel


class AICall(BaseModel):
    """One conversational AI call/session."""

    __tablename__ = "ai_calls"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    # External call identifier. We use the LiveKit room name here so the
    # call is greppable across the LiveKit, STT, TTS, and AI logs without
    # joining tables.
    call_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True
    )

    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    persona: Mapped[str | None] = mapped_column(String(64), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(16), nullable=True)
    playbook_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("playbooks.id"),
        nullable=True,
        index=True,
    )
    playbook_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AITranscriptEntry(BaseModel):
    """A single message in a call, persisted in the order it was emitted.

    We carry latency + token counts on the row so dashboards can build
    per-turn latency histograms without re-deriving from logs.
    """

    __tablename__ = "ai_transcript_entries"

    call_id: Mapped[str] = mapped_column(
        String(128), index=True, nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )
    turn_index: Mapped[int] = mapped_column(Integer, default=0)

    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)

    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# Composite index for the common "give me transcript for call X ordered" query.
Index(
    "ix_ai_transcript_call_turn",
    AITranscriptEntry.call_id,
    AITranscriptEntry.turn_index,
)


class AICallSummary(BaseModel):
    """End-of-call summary + qualification snapshot."""

    __tablename__ = "ai_call_summaries"

    call_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualification_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    qualification_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    qualification: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    total_turns: Mapped[int] = mapped_column(Integer, default=0)
    total_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
