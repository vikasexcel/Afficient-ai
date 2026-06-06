"""HTTP API for lead management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.auth.tenant import get_current_tenant
from modules.leads.schema import (
    AddLeadsToListInput,
    CreateLeadInput,
    CreateLeadListInput,
    LeadListLeadsResponse,
    LeadListOut,
    LeadListResponse,
    LeadOut,
    MembershipResponse,
    RemoveLeadsFromListInput,
    UpdateLeadInput,
    UpdateLeadListInput,
)
from modules.leads.service import LeadsService

router = APIRouter(prefix="/leads", tags=["leads"])
list_router = APIRouter(prefix="/lead-lists", tags=["lead-lists"])


def _org_id(tenant: dict) -> uuid.UUID:
    return uuid.UUID(str(tenant["organization_id"]))


def _user_id(tenant: dict) -> uuid.UUID | None:
    uid = tenant.get("user_id")
    return uuid.UUID(str(uid)) if uid else None


# ---------------------------------------------------------------------------
# Lead lists
# ---------------------------------------------------------------------------


@list_router.get("", response_model=LeadListResponse)
def list_lead_lists(
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    rows = LeadsService.list_lead_lists(db, _org_id(tenant))
    return LeadListResponse(
        lead_lists=[LeadListOut.model_validate(r) for r in rows]
    )


@list_router.post("", response_model=LeadListOut, status_code=201)
def create_lead_list(
    data: CreateLeadListInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    ll = LeadsService.create_lead_list(
        db, _org_id(tenant), _user_id(tenant), data
    )
    return LeadListOut.model_validate(ll)


@list_router.patch("/{list_id}", response_model=LeadListOut)
def update_lead_list(
    list_id: uuid.UUID,
    data: UpdateLeadListInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    ll = LeadsService.update_lead_list(
        db, _org_id(tenant), _user_id(tenant), list_id, data
    )
    return LeadListOut.model_validate(ll)


@list_router.delete("/{list_id}", status_code=204)
def delete_lead_list(
    list_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    LeadsService.delete_lead_list(db, _org_id(tenant), list_id)


@list_router.post("/{list_id}/leads", response_model=MembershipResponse, status_code=200)
def add_leads_to_list(
    list_id: uuid.UUID,
    data: AddLeadsToListInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    result = LeadsService.add_leads_to_list(
        db, _org_id(tenant), list_id, data.lead_ids
    )
    return MembershipResponse(**result)


@list_router.delete("/{list_id}/leads", response_model=MembershipResponse, status_code=200)
def remove_leads_from_list(
    list_id: uuid.UUID,
    data: RemoveLeadsFromListInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    result = LeadsService.remove_leads_from_list(
        db, _org_id(tenant), list_id, data.lead_ids
    )
    return MembershipResponse(**result)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


@router.get("", response_model=LeadListLeadsResponse)
def list_leads(
    lead_list_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    rows, total = LeadsService.list_leads(
        db,
        _org_id(tenant),
        lead_list_id=lead_list_id,
        search=search,
        status=status,
        limit=limit,
        offset=offset,
    )
    return LeadListLeadsResponse(
        leads=[LeadOut.model_validate(r) for r in rows],
        total=total,
    )


@router.post("", response_model=LeadOut, status_code=201)
def create_lead(
    data: CreateLeadInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    lead = LeadsService.create_lead(
        db, _org_id(tenant), _user_id(tenant), data
    )
    return LeadOut.model_validate(lead)


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    lead = LeadsService.get_lead(db, _org_id(tenant), lead_id)
    return LeadOut.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: uuid.UUID,
    data: UpdateLeadInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    lead = LeadsService.update_lead(
        db, _org_id(tenant), _user_id(tenant), lead_id, data
    )
    return LeadOut.model_validate(lead)


@router.delete("/{lead_id}", status_code=204)
def delete_lead(
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    LeadsService.delete_lead(
        db, _org_id(tenant), _user_id(tenant), lead_id
    )
