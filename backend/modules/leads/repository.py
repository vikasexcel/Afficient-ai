"""SQLAlchemy access layer for the leads module."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from modules.leads.model import Lead, LeadList, lead_list_memberships


class LeadListRepository:
    @staticmethod
    def list_by_org(
        db: Session, organization_id: uuid.UUID
    ) -> list[LeadList]:
        stmt = (
            select(LeadList)
            .where(LeadList.organization_id == organization_id)
            .order_by(LeadList.created_at.desc())
        )
        return list(db.execute(stmt).scalars())

    @staticmethod
    def get(
        db: Session, organization_id: uuid.UUID, list_id: uuid.UUID
    ) -> LeadList | None:
        stmt = select(LeadList).where(
            LeadList.id == list_id,
            LeadList.organization_id == organization_id,
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_by_name(
        db: Session, organization_id: uuid.UUID, name: str
    ) -> LeadList | None:
        stmt = select(LeadList).where(
            LeadList.organization_id == organization_id,
            func.lower(LeadList.name) == name.strip().lower(),
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def create(db: Session, lead_list: LeadList) -> LeadList:
        db.add(lead_list)
        db.flush()
        return lead_list

    @staticmethod
    def update(
        db: Session,
        lead_list: LeadList,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> LeadList:
        if name is not None:
            lead_list.name = name.strip()
        if description is not None:
            lead_list.description = description
        db.flush()
        return lead_list

    @staticmethod
    def delete(db: Session, lead_list: LeadList) -> None:
        db.delete(lead_list)


class LeadRepository:
    @staticmethod
    def list_by_org(
        db: Session,
        organization_id: uuid.UUID,
        *,
        lead_list_id: uuid.UUID | None = None,
        search: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[Lead], int]:
        base = (
            select(Lead)
            .where(Lead.organization_id == organization_id)
            .options(selectinload(Lead.lead_lists))
        )

        if lead_list_id is not None:
            # Filter to leads that are members of the given list.
            base = base.where(
                Lead.id.in_(
                    select(lead_list_memberships.c.lead_id).where(
                        lead_list_memberships.c.lead_list_id == lead_list_id
                    )
                )
            )

        if status is not None:
            base = base.where(Lead.status == status)

        term = (search or "").strip()
        if term:
            like = f"%{term.lower()}%"
            base = base.where(
                or_(
                    func.lower(func.coalesce(Lead.display_name, "")).like(like),
                    func.lower(Lead.first_name).like(like),
                    func.lower(func.coalesce(Lead.last_name, "")).like(like),
                    func.lower(func.coalesce(Lead.email, "")).like(like),
                    func.lower(Lead.phone).like(like),
                    func.lower(func.coalesce(Lead.company, "")).like(like),
                    func.lower(func.coalesce(Lead.job_title, "")).like(like),
                    func.lower(
                        func.coalesce(
                            func.array_to_string(Lead.tags, ","), ""
                        )
                    ).like(like),
                )
            )

        total_stmt = select(func.count()).select_from(
            base.order_by(None).subquery()
        )
        total = db.execute(total_stmt).scalar_one()

        stmt = (
            base.order_by(Lead.created_at.desc()).limit(limit).offset(offset)
        )
        rows = list(db.execute(stmt).scalars())
        return rows, int(total)

    @staticmethod
    def get(
        db: Session, organization_id: uuid.UUID, lead_id: uuid.UUID
    ) -> Lead | None:
        stmt = (
            select(Lead)
            .where(
                Lead.id == lead_id,
                Lead.organization_id == organization_id,
            )
            .options(selectinload(Lead.lead_lists))
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_by_normalized_phone(
        db: Session, organization_id: uuid.UUID, phone_normalized: str
    ) -> Lead | None:
        stmt = select(Lead).where(
            Lead.organization_id == organization_id,
            Lead.phone_normalized == phone_normalized,
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def existing_normalized_phones(
        db: Session, organization_id: uuid.UUID
    ) -> set[str]:
        rows = db.execute(
            select(Lead.phone_normalized).where(
                Lead.organization_id == organization_id
            )
        ).all()
        return {r[0] for r in rows if r[0]}

    @staticmethod
    def create(db: Session, lead: Lead) -> Lead:
        db.add(lead)
        db.flush()
        return lead

    @staticmethod
    def delete(db: Session, lead: Lead) -> None:
        db.delete(lead)


class LeadListMembershipRepository:
    @staticmethod
    def add(
        db: Session,
        lead: Lead,
        lead_list: LeadList,
    ) -> bool:
        """Add a lead to a list.  Returns True if added, False if already a member."""
        if lead_list in lead.lead_lists:
            return False
        lead.lead_lists.append(lead_list)
        db.flush()
        return True

    @staticmethod
    def remove(
        db: Session,
        lead: Lead,
        lead_list: LeadList,
    ) -> bool:
        """Remove a lead from a list.  Returns True if removed, False if not a member."""
        if lead_list not in lead.lead_lists:
            return False
        lead.lead_lists.remove(lead_list)
        db.flush()
        return True

    @staticmethod
    def clear_list(db: Session, lead_list_id: uuid.UUID) -> int:
        """Remove all membership rows for a given list.  Returns row count."""
        result = db.execute(
            delete(lead_list_memberships).where(
                lead_list_memberships.c.lead_list_id == lead_list_id
            )
        )
        return result.rowcount
