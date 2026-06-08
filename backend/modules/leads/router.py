"""HTTP API for lead management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
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
from modules.leads.csv_parser import (
    annotate_duplicates,
    detect_columns,
    normalize_phone,
    parse_csv_text,
    validate_row,
)

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
    from modules.leads.model import lead_list_memberships

    rows = LeadsService.list_lead_lists(db, _org_id(tenant))

    # Bulk-count memberships for all lists in one query.
    if rows:
        list_ids = [r.id for r in rows]
        count_rows = db.execute(
            select(
                lead_list_memberships.c.lead_list_id,
                func.count().label("cnt"),
            )
            .where(lead_list_memberships.c.lead_list_id.in_(list_ids))
            .group_by(lead_list_memberships.c.lead_list_id)
        ).all()
        counts: dict[str, int] = {str(r.lead_list_id): r.cnt for r in count_rows}
    else:
        counts = {}

    result: list[LeadListOut] = []
    for r in rows:
        out = LeadListOut.model_validate(r)
        out.lead_count = counts.get(str(r.id), 0)
        result.append(out)
    return LeadListResponse(lead_lists=result)


@list_router.post("", response_model=LeadListOut, status_code=201)
def create_lead_list(
    data: CreateLeadListInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    ll = LeadsService.create_lead_list(
        db, _org_id(tenant), _user_id(tenant), data
    )
    out = LeadListOut.model_validate(ll)
    out.lead_count = 0
    return out


@list_router.patch("/{list_id}", response_model=LeadListOut)
def update_lead_list(
    list_id: uuid.UUID,
    data: UpdateLeadListInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    from modules.leads.model import lead_list_memberships

    ll = LeadsService.update_lead_list(
        db, _org_id(tenant), _user_id(tenant), list_id, data
    )
    out = LeadListOut.model_validate(ll)
    row = db.execute(
        select(func.count()).select_from(lead_list_memberships).where(
            lead_list_memberships.c.lead_list_id == ll.id
        )
    ).scalar_one()
    out.lead_count = row or 0
    return out


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


@router.post("/import", status_code=200)
def import_leads_csv(
    file: UploadFile,
    lead_list_id: uuid.UUID | None = Form(default=None),
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    """Bulk-import leads from a CSV file.

    Accepts ``multipart/form-data`` with:
    - ``file``          — CSV file (required)
    - ``lead_list_id``  — UUID of an existing lead list to add imported leads to (optional)

    Returns a summary: ``{imported, skipped, errors: [{row, errors}]}``.
    """
    from modules.leads.model import Lead as LeadModel
    from modules.leads.repository import LeadRepository, LeadListMembershipRepository
    from sqlalchemy.exc import IntegrityError
    import re

    org_id = _org_id(tenant)
    user_id = _user_id(tenant)

    # ── Read & parse ────────────────────────────────────────────────────────
    raw_bytes = file.file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")  # strip BOM if present
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")

    try:
        rows, headers = parse_csv_text(text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not rows:
        raise HTTPException(400, "CSV has no data rows")

    columns = detect_columns(list(headers))

    if not columns.get("phone"):
        raise HTTPException(
            422,
            "CSV must have a 'phone' column (or a recognised synonym like 'mobile', 'telephone').",
        )

    # ── Validate rows ───────────────────────────────────────────────────────
    validated = [
        validate_row(row_number=i + 1, raw=r, columns=columns)
        for i, r in enumerate(rows)
    ]

    # ── Deduplicate against DB ───────────────────────────────────────────────
    existing_phones = LeadRepository.existing_normalized_phones(db, org_id)
    validated = annotate_duplicates(validated, existing_normalized_phones=existing_phones)

    # ── Validate lead list if provided ──────────────────────────────────────
    lead_list = None
    if lead_list_id is not None:
        from modules.leads.repository import LeadListRepository
        lead_list = LeadListRepository.get(db, org_id, lead_list_id)
        if lead_list is None:
            raise HTTPException(404, "Lead list not found")

    # ── Create leads ─────────────────────────────────────────────────────────
    imported = 0
    skipped = 0
    row_errors: list[dict] = []

    for row in validated:
        if row["status"] != "valid":
            skipped += 1
            row_errors.append({"row": row["row_number"], "errors": row["errors"]})
            continue

        # Split name into first / last.
        name = (row["name"] or "").strip()
        parts = name.split(None, 1)
        first_name = parts[0] if parts else name
        last_name = parts[1] if len(parts) > 1 else None

        phone_raw = row["phone"] or ""
        phone_normalized = normalize_phone(phone_raw)

        extra: dict = {}
        if row.get("industry"):
            extra["industry"] = row["industry"]
        if row.get("location"):
            extra["location"] = row["location"]
        if row.get("custom_fields"):
            extra.update(row["custom_fields"])

        lead = LeadModel(
            organization_id=org_id,
            display_name=row.get("display_name") or None,
            first_name=first_name,
            last_name=last_name,
            email=row.get("email") or None,
            phone=phone_raw,
            phone_normalized=phone_normalized,
            company=row.get("company") or None,
            tags=row.get("tags") or None,
            extra_data=extra or None,
        )

        try:
            db.add(lead)
            db.flush()
        except IntegrityError:
            db.rollback()
            skipped += 1
            row_errors.append(
                {"row": row["row_number"], "errors": ["phone already exists"]}
            )
            continue

        if lead_list is not None:
            lead.lead_lists.append(lead_list)

        imported += 1

    db.commit()

    return {"imported": imported, "skipped": skipped, "errors": row_errors}


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
