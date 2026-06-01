"""HTTP API for lead management + CSV upload."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.auth.tenant import get_current_tenant
from modules.leads.schema import (
    CommitUploadInput,
    CommitUploadResponse,
    CreateLeadListInput,
    LeadListLeadsResponse,
    LeadListOut,
    LeadListResponse,
    LeadOut,
    UploadPreviewResponse,
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
    return LeadListResponse(lead_lists=[LeadListOut.model_validate(r) for r in rows])


@list_router.post("", response_model=LeadListOut, status_code=201)
def create_lead_list(
    data: CreateLeadListInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    ll = LeadsService.create_lead_list(
        db,
        _org_id(tenant),
        _user_id(tenant),
        name=data.name,
        description=data.description,
        source=data.source,
    )
    return LeadListOut.model_validate(ll)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


@router.get("", response_model=LeadListLeadsResponse)
def list_leads(
    lead_list_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    rows, total = LeadsService.list_leads(
        db,
        _org_id(tenant),
        lead_list_id=lead_list_id,
        limit=limit,
        offset=offset,
    )
    return LeadListLeadsResponse(
        leads=[LeadOut.model_validate(r) for r in rows],
        total=total,
    )


@router.delete("/{lead_id}", status_code=204)
def delete_lead(
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    LeadsService.delete_lead(db, _org_id(tenant), lead_id)


# ---------------------------------------------------------------------------
# CSV upload
# ---------------------------------------------------------------------------


@router.post("/upload/preview", response_model=UploadPreviewResponse)
async def upload_preview(
    file: UploadFile = File(..., description="CSV file with header row"),
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are supported")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    return LeadsService.preview_upload(
        db, _org_id(tenant), raw_bytes=raw
    )


@router.post("/upload/commit", response_model=CommitUploadResponse)
def upload_commit(
    payload: CommitUploadInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    result = LeadsService.commit_upload(
        db, _org_id(tenant), _user_id(tenant), payload
    )
    return CommitUploadResponse(
        inserted=result["inserted"],
        skipped_duplicates=result["skipped_duplicates"],
        lead_list=LeadListOut.model_validate(result["lead_list"]),
    )
