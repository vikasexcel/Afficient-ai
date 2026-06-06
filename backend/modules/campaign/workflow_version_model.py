"""Immutable snapshot of a workflow graph at a point in time.

A ``WorkflowVersion`` record is created every time the graph definition of a
:class:`~modules.campaign.workflow_model.Workflow` changes, including when a
previous version is restored (restore = new version with the old content).

Design decisions
----------------
* Versions are **immutable** once written.  There is no ``updated_at`` column.
* ``version`` is an incrementing integer scoped to a single workflow (1, 2, 3…).
  The uniqueness is enforced both by a DB constraint and by the service layer.
* ``created_by`` is nullable — automated restorations (e.g. triggered by a
  migration or a system process) produce records with no user reference.
* We deliberately do **not** extend ``BaseModel`` (which would add an
  unwanted ``updated_at`` column).  ``id`` and ``created_at`` are defined
  explicitly here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class WorkflowVersion(Base):
    """An immutable snapshot of a workflow graph."""

    __tablename__ = "workflow_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Owning workflow — cascade delete keeps orphan cleanup automatic.
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Incrementing version number scoped to the workflow (1-based).
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Full graph snapshot at this version.
    nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    edges: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # The user who triggered this version, when known.
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        # Guarantee each version number appears at most once per workflow.
        UniqueConstraint(
            "workflow_id", "version",
            name="uq_workflow_versions_workflow_id_version",
        ),
        # Fast look-up: all versions for a workflow ordered by version.
        Index("ix_workflow_versions_workflow_id_version", "workflow_id", "version"),
    )
