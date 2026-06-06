"""ORM model for workflow templates.

A ``WorkflowTemplate`` is a reusable graph blueprint that can be cloned into a
campaign workflow or used as a starting point when building custom graphs.

Two categories of templates exist:

* **System templates** (``is_system=True``, ``organization_id=NULL``) — shipped
  with the product.  They are visible to every organisation but can only be
  read or cloned, never modified or deleted via the API.

* **Custom templates** (``is_system=False``, ``organization_id=<uuid>``) —
  created or cloned by an organisation.  They are visible only to that
  organisation and may be cloned or deleted.

The ``nodes`` / ``edges`` columns hold the same graph structure used by
``Workflow.nodes`` / ``Workflow.edges`` so templates can be applied directly
to a campaign's active workflow via a single PUT call.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import BaseModel


class WorkflowTemplate(BaseModel):
    """A reusable workflow graph blueprint."""

    __tablename__ = "workflow_templates"

    # NULL for system templates; FK for org-owned templates.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Short slug: "cold-outreach", "follow-up", "linkedin", "qualification",
    # "demo-booking", or any custom value ≤ 64 chars.
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # When True: visible to all orgs; cannot be modified or deleted.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Graph definition — same schema as Workflow.nodes / .edges.
    nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    edges: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


# Composite index for fast per-org + system template listing.
Index(
    "ix_workflow_templates_org_system",
    WorkflowTemplate.organization_id,
    WorkflowTemplate.is_system,
)
