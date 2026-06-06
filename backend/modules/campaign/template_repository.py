"""Data-access layer for workflow templates.

All SQL touching ``workflow_templates`` lives here.  Callers receive ORM
objects and commit themselves; the repository only flushes.

Visibility rules
----------------
* System templates (``is_system=True``, ``organization_id=NULL``) are visible
  to **every** organisation.
* Custom templates (``is_system=False``, ``organization_id=<uuid>``) are
  visible **only** to that organisation.

The :meth:`list` and :meth:`get` methods enforce these rules automatically so
callers never need to reason about ownership.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from modules.campaign.template_model import WorkflowTemplate


class WorkflowTemplateRepository:

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    @staticmethod
    def create(db: Session, template: WorkflowTemplate) -> WorkflowTemplate:
        """Persist a new template row and flush."""
        db.add(template)
        db.flush()
        return template

    @staticmethod
    def delete(db: Session, template: WorkflowTemplate) -> None:
        """Delete a template row (caller must verify it is not a system template)."""
        db.delete(template)
        db.flush()

    # ------------------------------------------------------------------ #
    # Single-row reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def get(
        db: Session,
        template_id: uuid.UUID,
        org_id: uuid.UUID | None = None,
    ) -> WorkflowTemplate | None:
        """Return a template by PK if accessible to *org_id*.

        Accessible means: is a system template OR belongs to *org_id*.
        When *org_id* is ``None`` only system templates are returned (useful
        for admin/seed paths).
        """
        stmt = select(WorkflowTemplate).where(WorkflowTemplate.id == template_id)
        if org_id is not None:
            stmt = stmt.where(
                or_(
                    WorkflowTemplate.is_system.is_(True),
                    WorkflowTemplate.organization_id == org_id,
                )
            )
        else:
            stmt = stmt.where(WorkflowTemplate.is_system.is_(True))
        return db.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Collection reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def list(
        db: Session,
        org_id: uuid.UUID | None = None,
        *,
        category: str | None = None,
        include_system: bool = True,
    ) -> list[WorkflowTemplate]:
        """Return all templates visible to *org_id*.

        * System templates are always included when *include_system* is True.
        * Org-owned templates are included when *org_id* is provided.
        * Results are ordered: system templates first (by name), then custom
          templates (by name).
        """
        conditions = []
        if include_system:
            conditions.append(WorkflowTemplate.is_system.is_(True))
        if org_id is not None:
            conditions.append(
                WorkflowTemplate.organization_id == org_id
            )

        if not conditions:
            return []

        stmt = (
            select(WorkflowTemplate)
            .where(or_(*conditions))
            .order_by(
                WorkflowTemplate.is_system.desc(),  # system first
                WorkflowTemplate.name.asc(),
            )
        )
        if category is not None:
            stmt = stmt.where(WorkflowTemplate.category == category)

        return list(db.execute(stmt).scalars())

    # ------------------------------------------------------------------ #
    # Clone
    # ------------------------------------------------------------------ #

    @staticmethod
    def clone(
        db: Session,
        source: WorkflowTemplate,
        *,
        org_id: uuid.UUID,
        name: str | None = None,
    ) -> WorkflowTemplate:
        """Create an org-owned copy of *source* and flush.

        The clone is always ``is_system=False`` and scoped to *org_id*.
        ``name`` defaults to ``"Copy of <source.name>"``.
        """
        clone = WorkflowTemplate(
            organization_id=org_id,
            name=name or f"Copy of {source.name}",
            description=source.description,
            category=source.category,
            is_system=False,
            nodes=list(source.nodes or []),
            edges=list(source.edges or []),
        )
        db.add(clone)
        db.flush()
        return clone
