"""Business logic for the leads module."""

from __future__ import annotations

import re
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.auth.audit_model import AuditLog
from modules.auth.repository import AuthRepository
from modules.leads.model import Lead, LeadList
from modules.leads.repository import (
    LeadListMembershipRepository,
    LeadListRepository,
    LeadRepository,
)
from modules.leads.schema import (
    CreateLeadInput,
    CreateLeadListInput,
    UpdateLeadInput,
    UpdateLeadListInput,
)


def _normalize_phone(raw: str) -> str:
    """Return digits-only version of a phone number for dedupe."""
    return re.sub(r"\D", "", raw or "")


def _audit(
    db: Session,
    user_id: uuid.UUID | None,
    action: str,
    details: str,
) -> None:
    AuthRepository.create_audit(
        db,
        AuditLog(
            user_id=user_id,
            action=action,
            details=details,
        ),
    )


class LeadsService:
    # ------------------------------------------------------------------ #
    # Lead lists
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_lead_lists(
        db: Session, organization_id: uuid.UUID
    ) -> list[LeadList]:
        return LeadListRepository.list_by_org(db, organization_id)

    @staticmethod
    def get_lead_list(
        db: Session, organization_id: uuid.UUID, list_id: uuid.UUID
    ) -> LeadList:
        ll = LeadListRepository.get(db, organization_id, list_id)
        if ll is None:
            raise HTTPException(404, "Lead list not found")
        return ll

    @staticmethod
    def create_lead_list(
        db: Session,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        data: CreateLeadListInput,
    ) -> LeadList:
        existing = LeadListRepository.get_by_name(
            db, organization_id, data.name
        )
        if existing is not None:
            raise HTTPException(
                409, "A lead list with that name already exists"
            )

        ll = LeadList(
            organization_id=organization_id,
            name=data.name.strip(),
            description=data.description,
        )
        try:
            LeadListRepository.create(db, ll)
            _audit(
                db,
                user_id,
                "LEAD_LIST_CREATED",
                f"list={ll.name} org={organization_id}",
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                409, "A lead list with that name already exists"
            )

        db.refresh(ll)
        return ll

    @staticmethod
    def update_lead_list(
        db: Session,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        list_id: uuid.UUID,
        data: UpdateLeadListInput,
    ) -> LeadList:
        ll = LeadListRepository.get(db, organization_id, list_id)
        if ll is None:
            raise HTTPException(404, "Lead list not found")

        if data.name is not None and data.name.strip() != ll.name:
            clash = LeadListRepository.get_by_name(
                db, organization_id, data.name
            )
            if clash is not None and clash.id != ll.id:
                raise HTTPException(
                    409, "A lead list with that name already exists"
                )

        try:
            LeadListRepository.update(
                db,
                ll,
                name=data.name,
                description=data.description,
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                409, "A lead list with that name already exists"
            )

        db.refresh(ll)
        return ll

    @staticmethod
    def delete_lead_list(
        db: Session,
        organization_id: uuid.UUID,
        list_id: uuid.UUID,
    ) -> None:
        ll = LeadListRepository.get(db, organization_id, list_id)
        if ll is None:
            raise HTTPException(404, "Lead list not found")
        LeadListMembershipRepository.clear_list(db, list_id)
        LeadListRepository.delete(db, ll)
        db.commit()

    # ------------------------------------------------------------------ #
    # Leads — CRUD
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_leads(
        db: Session,
        organization_id: uuid.UUID,
        *,
        lead_list_id: uuid.UUID | None = None,
        search: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[Lead], int]:
        return LeadRepository.list_by_org(
            db,
            organization_id,
            lead_list_id=lead_list_id,
            search=search,
            status=status,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def get_lead(
        db: Session, organization_id: uuid.UUID, lead_id: uuid.UUID
    ) -> Lead:
        lead = LeadRepository.get(db, organization_id, lead_id)
        if lead is None:
            raise HTTPException(404, "Lead not found")
        return lead

    @staticmethod
    def create_lead(
        db: Session,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        data: CreateLeadInput,
    ) -> Lead:
        normalized = _normalize_phone(data.phone)
        if len(normalized) < 7:
            raise HTTPException(422, "phone is not a valid number")

        if (
            LeadRepository.get_by_normalized_phone(
                db, organization_id, normalized
            )
            is not None
        ):
            raise HTTPException(
                409, "A lead with that phone number already exists"
            )

        # Validate lead list memberships before inserting.
        lists: list[LeadList] = []
        for lid in data.lead_list_ids or []:
            ll = LeadListRepository.get(db, organization_id, lid)
            if ll is None:
                raise HTTPException(
                    404, f"Lead list {lid} not found"
                )
            lists.append(ll)

        lead = Lead(
            organization_id=organization_id,
            display_name=data.display_name,
            first_name=data.first_name.strip(),
            last_name=(data.last_name.strip() if data.last_name else None),
            email=data.email,
            phone=data.phone.strip(),
            phone_normalized=normalized,
            linkedin_url=data.linkedin_url,
            company=data.company,
            job_title=data.job_title,
            status=data.status,
            tags=sorted(set(data.tags)) if data.tags else None,
            extra_data=data.extra_data,
        )
        try:
            LeadRepository.create(db, lead)
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                409, "A lead with that phone number already exists"
            ) from exc

        for ll in lists:
            lead.lead_lists.append(ll)

        _audit(
            db,
            user_id,
            "LEAD_CREATED",
            f"lead={lead.id} phone={lead.phone} org={organization_id}",
        )
        db.commit()
        db.refresh(lead)
        return lead

    @staticmethod
    def update_lead(
        db: Session,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        lead_id: uuid.UUID,
        data: UpdateLeadInput,
    ) -> Lead:
        lead = LeadRepository.get(db, organization_id, lead_id)
        if lead is None:
            raise HTTPException(404, "Lead not found")

        fields = data.model_dump(exclude_unset=True)

        if "phone" in fields and fields["phone"] is not None:
            normalized = _normalize_phone(fields["phone"])
            if len(normalized) < 7:
                raise HTTPException(422, "phone is not a valid number")
            clash = LeadRepository.get_by_normalized_phone(
                db, organization_id, normalized
            )
            if clash is not None and clash.id != lead.id:
                raise HTTPException(
                    409, "Another lead already uses that phone number"
                )
            lead.phone = fields["phone"].strip()
            lead.phone_normalized = normalized

        if "first_name" in fields and fields["first_name"] is not None:
            lead.first_name = fields["first_name"].strip()

        if "last_name" in fields:
            last = fields["last_name"]
            lead.last_name = last.strip() if last else None

        if "tags" in fields:
            tags = fields["tags"]
            lead.tags = sorted(set(tags)) if tags else None

        for attr in (
            "display_name",
            "email",
            "linkedin_url",
            "company",
            "job_title",
            "status",
            "extra_data",
        ):
            if attr in fields:
                setattr(lead, attr, fields[attr])

        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                409, "Another lead already uses that phone number"
            ) from exc

        _audit(
            db,
            user_id,
            "LEAD_UPDATED",
            f"lead={lead.id} fields={list(fields.keys())} org={organization_id}",
        )
        db.commit()
        db.refresh(lead)
        return lead

    @staticmethod
    def delete_lead(
        db: Session,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        lead_id: uuid.UUID,
    ) -> None:
        lead = LeadRepository.get(db, organization_id, lead_id)
        if lead is None:
            raise HTTPException(404, "Lead not found")

        _audit(
            db,
            user_id,
            "LEAD_DELETED",
            f"lead={lead_id} phone={lead.phone} org={organization_id}",
        )
        LeadRepository.delete(db, lead)
        db.commit()

    # ------------------------------------------------------------------ #
    # Lead list memberships
    # ------------------------------------------------------------------ #

    @staticmethod
    def add_leads_to_list(
        db: Session,
        organization_id: uuid.UUID,
        list_id: uuid.UUID,
        lead_ids: list[uuid.UUID],
    ) -> dict:
        ll = LeadListRepository.get(db, organization_id, list_id)
        if ll is None:
            raise HTTPException(404, "Lead list not found")

        added = already_member = 0
        for lead_id in lead_ids:
            lead = LeadRepository.get(db, organization_id, lead_id)
            if lead is None:
                raise HTTPException(404, f"Lead {lead_id} not found")
            if LeadListMembershipRepository.add(db, lead, ll):
                added += 1
            else:
                already_member += 1

        db.commit()
        return {"added": added, "already_member": already_member}

    @staticmethod
    def remove_leads_from_list(
        db: Session,
        organization_id: uuid.UUID,
        list_id: uuid.UUID,
        lead_ids: list[uuid.UUID],
    ) -> dict:
        ll = LeadListRepository.get(db, organization_id, list_id)
        if ll is None:
            raise HTTPException(404, "Lead list not found")

        removed = not_member = 0
        for lead_id in lead_ids:
            lead = LeadRepository.get(db, organization_id, lead_id)
            if lead is None:
                raise HTTPException(404, f"Lead {lead_id} not found")
            if LeadListMembershipRepository.remove(db, lead, ll):
                removed += 1
            else:
                not_member += 1

        db.commit()
        return {"removed": removed, "not_member": not_member}
