"""SQLAlchemy access for the leads module."""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.leads.model import Lead, LeadList


class LeadListRepository:
    @staticmethod
    def list_by_org(db: Session, organization_id: uuid.UUID) -> list[LeadList]:
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
    def refresh_count(db: Session, list_id: uuid.UUID) -> int:
        count = db.execute(
            select(func.count(Lead.id)).where(Lead.lead_list_id == list_id)
        ).scalar_one()
        ll = db.get(LeadList, list_id)
        if ll is not None:
            ll.lead_count = int(count)
        return int(count)


class LeadRepository:
    @staticmethod
    def list_by_org(
        db: Session,
        organization_id: uuid.UUID,
        *,
        lead_list_id: uuid.UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[Lead], int]:
        base = select(Lead).where(Lead.organization_id == organization_id)
        if lead_list_id is not None:
            base = base.where(Lead.lead_list_id == lead_list_id)

        total = db.execute(
            select(func.count())
            .select_from(base.subquery())
        ).scalar_one()

        stmt = (
            base.order_by(Lead.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list(db.execute(stmt).scalars())
        return rows, int(total)

    @staticmethod
    def get(
        db: Session, organization_id: uuid.UUID, lead_id: uuid.UUID
    ) -> Lead | None:
        stmt = select(Lead).where(
            Lead.id == lead_id, Lead.organization_id == organization_id
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
    def bulk_insert(db: Session, leads: Iterable[Lead]) -> int:
        count = 0
        for lead in leads:
            db.add(lead)
            count += 1
        if count:
            db.flush()
        return count

    @staticmethod
    def delete(db: Session, lead: Lead) -> None:
        db.delete(lead)
