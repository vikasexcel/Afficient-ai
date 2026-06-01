"""Persistence models for the leads module.

A ``Lead`` is an org-scoped contact record. Leads optionally belong to a
``LeadList`` so users can segment them by campaign, source, etc. Both
tables are tenant-scoped via ``organization_id`` and rely on a unique
constraint on the *normalized* phone (digits only, with country code) to
enforce duplicate detection at the database boundary — defense in depth
behind the validator that runs on upload.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    ARRAY,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import BaseModel


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


class LeadList(BaseModel):
    """A named, segmentable collection of leads."""

    __tablename__ = "lead_lists"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lead_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    leads: Mapped[list["Lead"]] = relationship(
        "Lead", back_populates="lead_list", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_lead_lists_org_name"
        ),
    )


class Lead(BaseModel):
    """A single lead. Phone is required + unique per org for dedupe."""

    __tablename__ = "leads"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    lead_list_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lead_lists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    # Normalized digits-only phone used for uniqueness + duplicate detection.
    phone_normalized: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default=LEAD_STATUS_NEW, nullable=False, index=True
    )

    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    # Free-form per-lead extras captured during upload (e.g. seniority,
    # job title, custom CRM keys we don't have first-class columns for).
    custom_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    lead_list: Mapped["LeadList | None"] = relationship(
        "LeadList", back_populates="leads"
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "phone_normalized",
            name="uq_leads_org_phone",
        ),
    )


# Common access pattern: "list leads for org, newest first".
Index(
    "ix_leads_org_created",
    Lead.organization_id,
    Lead.created_at,
)
