"""ORM models for the email conversation/threading system.

An ``EmailConversation`` is created the moment the workflow agent sends the
first email to a lead.  Every subsequent reply (either direction) is stored
as an ``EmailMessage`` row so the full history is available for LLM context.

Thread continuity
-----------------
RFC 2822 threading works via two headers:

* **In-Reply-To** — the ``Message-ID`` of the *immediately preceding* message
  the replier is responding to.
* **References** — the full ordered chain of all ancestor ``Message-ID``
  values separated by spaces.

``EmailConversation`` maintains both:

* ``last_message_id`` — used as the next reply's ``In-Reply-To`` value.
* ``references_chain`` — space-separated list of all prior ``Message-ID``
  values; appended to form the ``References`` header of each new send.

This ensures Gmail/Outlook/Apple Mail all group the full exchange as a single
thread regardless of whether they honour ``In-Reply-To`` or ``References``.

Lead isolation
--------------
Every conversation row is scoped to ``(organization_id, lead_id,
execution_id)`` so replies for Lead A can never be matched to Lead B's
execution.  The inbound webhook looks up the conversation by ``root_message_id``
or any ``message_id`` in the thread — both are guaranteed unique globally by
``make_msgid()``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, BaseModel


# ---------------------------------------------------------------------------
# EmailConversation — one row per lead per campaign run
# ---------------------------------------------------------------------------


class EmailConversation(BaseModel):
    """Tracks an ongoing email thread between the agent and a single lead.

    Created when the EMAIL node fires.  Updated on every inbound webhook
    delivery and every AI reply sent.
    """

    __tablename__ = "email_conversations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable — pre-webhook executions may lack an execution row reference.
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # The Message-ID of the first outbound email — the webhook uses this to
    # match incoming In-Reply-To / References values.
    root_message_id: Mapped[str] = mapped_column(String(512), nullable=False)

    # Message-ID of the most recent message in the thread (either direction).
    # Used as the ``In-Reply-To`` value of the next reply we send.
    last_message_id: Mapped[str] = mapped_column(String(512), nullable=False)

    # Space-separated ordered list of all Message-IDs seen so far.
    # Appended to form the RFC 2822 ``References`` header on every new send.
    references_chain: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Subject line of the original email (used when generating replies so the
    # LLM has context about the topic without loading every prior message).
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")

    # Lead's email address — captured at create-time for quick lookup.
    lead_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # "active" while the conversation is ongoing; "closed" once a STOP node
    # is reached or the lead opts out.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    # 1-based count of turns completed (each send + reply pair = 1 turn).
    turn_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Maximum number of AI reply turns allowed before the conversation closes
    # automatically (prevents infinite loops).
    max_turns: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )


# Composite index: look up active conversations for a lead quickly.
Index(
    "ix_email_conversations_lead_status",
    EmailConversation.lead_id,
    EmailConversation.status,
)
# Look up by Message-ID (inbound webhook path — called on every reply).
Index(
    "ix_email_conversations_root_message_id",
    EmailConversation.root_message_id,
)


# ---------------------------------------------------------------------------
# EmailMessage — one row per individual email in the thread
# ---------------------------------------------------------------------------

ROLE_AGENT = "agent"
ROLE_LEAD = "lead"


class EmailMessage(BaseModel):
    """A single email message belonging to a conversation thread."""

    __tablename__ = "email_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # "agent" = outbound email sent by the system; "lead" = inbound reply.
    role: Mapped[str] = mapped_column(String(10), nullable=False)

    # The RFC 2822 ``Message-ID`` header value (angle-bracket form).
    message_id: Mapped[str] = mapped_column(String(512), nullable=False)

    # Headers from the *incoming* reply; NULL for agent-sent messages.
    in_reply_to: Mapped[str | None] = mapped_column(String(512), nullable=True)
    references: Mapped[str | None] = mapped_column(Text, nullable=True)

    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ISO-8601 timestamp of when the message was sent or received.
    sent_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# Index for fast lookup of all messages in a conversation (timeline view).
Index(
    "ix_email_messages_conv_sent",
    EmailMessage.conversation_id,
    EmailMessage.sent_at,
)
