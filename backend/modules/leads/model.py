"""Persistence models for the leads module.

Design decisions
----------------
* Lead ↔ LeadList is **many-to-many** via ``lead_list_memberships`` so a
  single lead can belong to multiple lists / campaigns without duplicating
  contact data.
* ``phone_normalized`` (digits-only) enforces per-org uniqueness at the DB
  layer and powers fast duplicate detection regardless of how users format
  numbers (+1-555-555-5555 vs 15555555555 etc).
* ``extra_data`` is a free-form JSON blob for arbitrary per-lead metadata
  (CRM IDs, custom attributes from imports, etc.).  The column is named
  ``extra_data`` to avoid shadowing SQLAlchemy's reserved ``metadata``
  descriptor on ``DeclarativeBase``.
* Tenant isolation is enforced at every row via ``organization_id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    ARRAY,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, BaseModel


# ---------------------------------------------------------------------------
# Many-to-many association table (no extra columns needed here)
# ---------------------------------------------------------------------------

lead_list_memberships = Table(
    "lead_list_memberships",
    Base.metadata,
    Column(
        "lead_id",
        ForeignKey("leads.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "lead_list_id",
        ForeignKey("lead_lists.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "created_at",
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    ),
)


# ---------------------------------------------------------------------------
# Lead status vocabulary
# ---------------------------------------------------------------------------

LEAD_STATUS_NEW = "new"
LEAD_STATUS_CONTACTED = "contacted"
LEAD_STATUS_QUALIFIED = "qualified"
LEAD_STATUS_CONVERTED = "converted"
LEAD_STATUS_LOST = "lost"

ALL_LEAD_STATUSES = frozenset(
    {
        LEAD_STATUS_NEW,
        LEAD_STATUS_CONTACTED,
        LEAD_STATUS_QUALIFIED,
        LEAD_STATUS_CONVERTED,
        LEAD_STATUS_LOST,
    }
)


# ---------------------------------------------------------------------------
# LeadList
# ---------------------------------------------------------------------------


class LeadList(BaseModel):
    """A named, org-scoped collection of leads."""

    __tablename__ = "lead_lists"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    leads: Mapped[list["Lead"]] = relationship(
        "Lead",
        secondary="lead_list_memberships",
        back_populates="lead_lists",
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_lead_lists_org_name"
        ),
    )


# ---------------------------------------------------------------------------
# Lead
# ---------------------------------------------------------------------------


class Lead(BaseModel):
    """A single contact record.  Phone is unique per org for dedupe."""

    __tablename__ = "leads"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    # Optional override for how this lead is labelled in the UI and in calls.
    # Falls back to first_name + last_name when NULL (backward-compatible).
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    # Digits-only copy used for uniqueness constraint + duplicate detection.
    phone_normalized: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    linkedin_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32),
        default=LEAD_STATUS_NEW,
        nullable=False,
        index=True,
    )

    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    # Free-form arbitrary metadata (CRM ids, import extras, custom fields).
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    lead_lists: Mapped[list["LeadList"]] = relationship(
        "LeadList",
        secondary="lead_list_memberships",
        back_populates="leads",
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "phone_normalized",
            name="uq_leads_org_phone",
        ),
    )


# Composite index: common access pattern "list leads for org, newest first".
Index("ix_leads_org_created", Lead.organization_id, Lead.created_at)


# ---------------------------------------------------------------------------
# LeadActivity vocabulary
# ---------------------------------------------------------------------------

ACTIVITY_EMAIL_SENT = "email_sent"
ACTIVITY_EMAIL_FAILED = "email_failed"

# LinkedIn activity types — constrained to VARCHAR(16) by the DB schema.
ACTIVITY_LI_CONNECT = "li_connect"   # connection request sent
ACTIVITY_LI_MESSAGE = "li_message"   # direct message sent
ACTIVITY_LI_FAILED  = "li_failed"    # any LinkedIn action failure

# Call activity types
ACTIVITY_CALL_INIT      = "call_init"    # call placed / dialling
ACTIVITY_CALL_COMPLETED = "call_done"    # call completed successfully
ACTIVITY_CALL_FAILED    = "call_fail"    # call failed

# Workflow-level activity types
ACTIVITY_WF_STARTED     = "wf_start"    # lead entered workflow
ACTIVITY_WF_COMPLETED   = "wf_done"     # lead reached STOP node
ACTIVITY_REPLY_RECEIVED = "reply_recv"  # email reply detected
ACTIVITY_REPLY_NEGATIVE = "reply_neg"   # negative / opt-out reply detected
ACTIVITY_COND_EVAL      = "cond_eval"   # condition node evaluated


# ---------------------------------------------------------------------------
# LeadActivity
# ---------------------------------------------------------------------------


class LeadActivity(BaseModel):
    """An audit-trail entry for actions taken on a lead.

    The table was created by migration ``m8h9i0j1k2l3``.
    ``activity_type`` is constrained to ``VARCHAR(16)`` in the DB; all
    registered constants are ≤ 12 characters.
    """

    __tablename__ = "lead_activities"

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
    # ``user_id`` is NULL for system-generated activities (e.g. campaign email).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    # Short identifier; see ACTIVITY_* constants above.
    activity_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
