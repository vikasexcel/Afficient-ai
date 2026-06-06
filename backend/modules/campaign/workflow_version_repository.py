"""Data-access layer for workflow versions.

All SQL touching ``workflow_versions`` is concentrated here.  Every method
flushes but does **not** commit — callers own the transaction boundary.

Versioning contract
-------------------
* Version numbers are 1-based and increment monotonically per workflow.
* The repository is responsible only for persistence and reads.  The business
  rules (detect graph changes, decide when to create a version, restore logic)
  live in :class:`~modules.campaign.workflow_service.WorkflowService`.
* Deleting version records is intentionally unsupported — history must never
  be destroyed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.campaign.workflow_model import Workflow
from modules.campaign.workflow_version_model import WorkflowVersion


class WorkflowVersionRepository:

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    @staticmethod
    def create_version(
        db: Session,
        *,
        workflow_id: uuid.UUID,
        version: int,
        nodes: list,
        edges: list,
        created_by: uuid.UUID | None = None,
    ) -> WorkflowVersion:
        """Persist a new immutable version record and flush."""
        record = WorkflowVersion(
            workflow_id=workflow_id,
            version=version,
            nodes=list(nodes),
            edges=list(edges),
            created_by=created_by,
        )
        db.add(record)
        db.flush()
        return record

    @staticmethod
    def restore_version(
        db: Session,
        workflow: Workflow,
        version_record: WorkflowVersion,
    ) -> Workflow:
        """Copy the graph snapshot from *version_record* onto *workflow* and flush.

        This is a pure data operation — the caller (``WorkflowService``) is
        responsible for creating the new version record before calling this.
        """
        workflow.nodes = list(version_record.nodes or [])
        workflow.edges = list(version_record.edges or [])
        db.flush()
        return workflow

    # ------------------------------------------------------------------ #
    # Single-row reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_version(
        db: Session,
        workflow_id: uuid.UUID,
        version: int,
    ) -> WorkflowVersion | None:
        """Return the version record for a specific version number, or None."""
        return db.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.version == version,
            )
        ).scalar_one_or_none()

    @staticmethod
    def latest_version(
        db: Session,
        workflow_id: uuid.UUID,
    ) -> WorkflowVersion | None:
        """Return the most-recently created version record, or None."""
        return db.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .limit(1)
        ).scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Collection reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_versions(
        db: Session,
        workflow_id: uuid.UUID,
    ) -> list[WorkflowVersion]:
        """Return all version records for a workflow, newest-first."""
        return list(
            db.execute(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == workflow_id)
                .order_by(WorkflowVersion.version.desc())
            ).scalars()
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def next_version_number(
        db: Session,
        workflow_id: uuid.UUID,
    ) -> int:
        """Return the next version number (max existing version + 1, or 1)."""
        result = db.execute(
            select(func.max(WorkflowVersion.version)).where(
                WorkflowVersion.workflow_id == workflow_id
            )
        ).scalar_one_or_none()
        return (result or 0) + 1
