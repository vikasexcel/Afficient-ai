"""Business logic for the leads module."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.leads.csv_parser import (
    annotate_duplicates,
    detect_columns,
    normalize_phone,
    parse_csv_text,
    validate_row,
)
from modules.leads.model import Lead, LeadActivity, LeadList
from modules.leads.repository import (
    LeadActivityRepository,
    LeadListRepository,
    LeadRepository,
)
from modules.leads.schema import (
    CommitUploadInput,
    CreateLeadInput,
    UpdateLeadInput,
    UploadParsedRow,
    UploadPreviewResponse,
)


MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB cap on raw CSV upload.
MAX_PREVIEW_ROWS = 5_000


class LeadsService:
    # ------------------------------------------------------------------ #
    # Lead lists
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_lead_lists(db: Session, organization_id: uuid.UUID):
        return LeadListRepository.list_by_org(db, organization_id)

    @staticmethod
    def create_lead_list(
        db: Session,
        organization_id: uuid.UUID,
        created_by: uuid.UUID | None,
        *,
        name: str,
        description: str | None = None,
        source: str | None = None,
    ) -> LeadList:
        existing = LeadListRepository.get_by_name(db, organization_id, name)
        if existing is not None:
            raise HTTPException(409, "A lead list with that name already exists")

        ll = LeadList(
            organization_id=organization_id,
            created_by=created_by,
            name=name.strip(),
            description=description,
            source=source,
        )
        LeadListRepository.create(db, ll)
        db.commit()
        db.refresh(ll)
        return ll

    # ------------------------------------------------------------------ #
    # Leads
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_leads(
        db: Session,
        organization_id: uuid.UUID,
        *,
        lead_list_id: uuid.UUID | None,
        search: str | None = None,
        limit: int,
        offset: int,
    ):
        return LeadRepository.list_by_org(
            db,
            organization_id,
            lead_list_id=lead_list_id,
            search=search,
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
        data: CreateLeadInput,
    ) -> Lead:
        normalized = normalize_phone(data.phone)
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

        if data.lead_list_id is not None:
            ll = LeadListRepository.get(
                db, organization_id, data.lead_list_id
            )
            if ll is None:
                raise HTTPException(404, "Lead list not found")

        lead = Lead(
            organization_id=organization_id,
            lead_list_id=data.lead_list_id,
            name=data.name.strip(),
            email=data.email,
            phone=data.phone.strip(),
            phone_normalized=normalized,
            company=data.company,
            industry=data.industry,
            location=data.location,
            source=data.source,
            status=data.status,
            tags=sorted(set(data.tags)) if data.tags else None,
            custom_fields=data.custom_fields,
            notes=data.notes,
        )
        try:
            LeadRepository.create(db, lead)
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                409, "A lead with that phone number already exists"
            ) from exc

        if data.lead_list_id is not None:
            LeadListRepository.refresh_count(db, data.lead_list_id)
        db.commit()
        db.refresh(lead)
        return lead

    @staticmethod
    def update_lead(
        db: Session,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        data: UpdateLeadInput,
    ) -> Lead:
        lead = LeadRepository.get(db, organization_id, lead_id)
        if lead is None:
            raise HTTPException(404, "Lead not found")

        fields = data.model_dump(exclude_unset=True)
        old_list_id = lead.lead_list_id

        # Phone needs special handling: keep ``phone_normalized`` in sync
        # and re-check the per-org uniqueness constraint.
        if "phone" in fields and fields["phone"] is not None:
            normalized = normalize_phone(fields["phone"])
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

        if "name" in fields and fields["name"] is not None:
            lead.name = fields["name"].strip()
        if "tags" in fields:
            tags = fields["tags"]
            lead.tags = sorted(set(tags)) if tags else None

        for attr in (
            "email",
            "company",
            "industry",
            "location",
            "source",
            "status",
            "custom_fields",
            "notes",
        ):
            if attr in fields:
                setattr(lead, attr, fields[attr])

        if "lead_list_id" in fields:
            new_list_id = fields["lead_list_id"]
            if new_list_id is not None:
                ll = LeadListRepository.get(
                    db, organization_id, new_list_id
                )
                if ll is None:
                    raise HTTPException(404, "Lead list not found")
            lead.lead_list_id = new_list_id

        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                409, "Another lead already uses that phone number"
            ) from exc

        # Keep both source and destination list counts accurate.
        for list_id in {old_list_id, lead.lead_list_id}:
            if list_id is not None:
                LeadListRepository.refresh_count(db, list_id)

        db.commit()
        db.refresh(lead)
        return lead

    @staticmethod
    def delete_lead(
        db: Session, organization_id: uuid.UUID, lead_id: uuid.UUID
    ) -> None:
        lead = LeadRepository.get(db, organization_id, lead_id)
        if lead is None:
            raise HTTPException(404, "Lead not found")
        list_id = lead.lead_list_id
        LeadRepository.delete(db, lead)
        db.flush()
        if list_id is not None:
            LeadListRepository.refresh_count(db, list_id)
        db.commit()

    # ------------------------------------------------------------------ #
    # Lead activities
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_activities(
        db: Session,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
    ) -> list[LeadActivity]:
        # Ensure the lead exists + belongs to the org before listing.
        if LeadRepository.get(db, organization_id, lead_id) is None:
            raise HTTPException(404, "Lead not found")
        return LeadActivityRepository.list_for_lead(
            db, organization_id, lead_id
        )

    @staticmethod
    def log_activity(
        db: Session,
        organization_id: uuid.UUID,
        user_id: uuid.UUID | None,
        lead_id: uuid.UUID,
        *,
        activity_type: str,
        notes: str | None,
    ) -> LeadActivity:
        if LeadRepository.get(db, organization_id, lead_id) is None:
            raise HTTPException(404, "Lead not found")

        activity = LeadActivity(
            organization_id=organization_id,
            lead_id=lead_id,
            user_id=user_id,
            activity_type=activity_type,
            notes=(notes.strip() if notes else None),
        )
        LeadActivityRepository.create(db, activity)
        db.commit()
        db.refresh(activity)
        return activity

    # ------------------------------------------------------------------ #
    # CSV upload
    # ------------------------------------------------------------------ #

    @staticmethod
    def preview_upload(
        db: Session,
        organization_id: uuid.UUID,
        *,
        raw_bytes: bytes,
    ) -> UploadPreviewResponse:
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413,
                f"CSV too large (>{MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
            )

        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw_bytes.decode("latin-1")
            except UnicodeDecodeError as exc:
                raise HTTPException(
                    400, f"Could not decode CSV: {exc}"
                ) from exc

        try:
            raw_rows, headers = parse_csv_text(text)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        if len(raw_rows) > MAX_PREVIEW_ROWS:
            raise HTTPException(
                413,
                f"CSV has too many rows (max {MAX_PREVIEW_ROWS:,})",
            )

        columns = detect_columns(headers)
        if not columns["name"] or not columns["phone"]:
            raise HTTPException(
                400,
                "CSV must include at least a 'name' and a 'phone' column "
                "(synonyms accepted: full_name, mobile, etc.)",
            )

        existing_phones = LeadRepository.existing_normalized_phones(
            db, organization_id
        )

        parsed = [
            validate_row(
                row_number=idx + 2,  # +1 for 0-index, +1 for header row.
                raw=row,
                columns=columns,
            )
            for idx, row in enumerate(raw_rows)
        ]
        parsed = annotate_duplicates(
            parsed, existing_normalized_phones=existing_phones
        )

        stats = {
            "total": len(parsed),
            "valid": sum(1 for r in parsed if r["status"] == "valid"),
            "invalid": sum(1 for r in parsed if r["status"] == "invalid"),
            "duplicate": sum(1 for r in parsed if r["status"] == "duplicate"),
        }

        return UploadPreviewResponse(
            rows=[UploadParsedRow(**r) for r in parsed],
            detected_columns=columns,
            stats=stats,
        )

    @staticmethod
    def commit_upload(
        db: Session,
        organization_id: uuid.UUID,
        created_by: uuid.UUID | None,
        payload: CommitUploadInput,
    ):
        # Resolve target lead list ---------------------------------------------
        lead_list: LeadList | None = None
        if payload.lead_list_id is not None:
            lead_list = LeadListRepository.get(
                db, organization_id, payload.lead_list_id
            )
            if lead_list is None:
                raise HTTPException(404, "Lead list not found")
        elif payload.new_list_name:
            existing = LeadListRepository.get_by_name(
                db, organization_id, payload.new_list_name
            )
            if existing is not None:
                lead_list = existing
            else:
                lead_list = LeadList(
                    organization_id=organization_id,
                    created_by=created_by,
                    name=payload.new_list_name.strip(),
                    source=payload.source,
                )
                LeadListRepository.create(db, lead_list)
        else:
            raise HTTPException(
                400, "Provide either lead_list_id or new_list_name"
            )

        # Build Lead rows + skip duplicates -----------------------------------
        existing_phones = LeadRepository.existing_normalized_phones(
            db, organization_id
        )
        seg = payload.segmentation
        merged_tags = list(seg.tags)

        inserted = 0
        skipped = 0
        rows_to_insert: list[Lead] = []

        for row in payload.rows:
            normalized = normalize_phone(row.phone)
            if not normalized or normalized in existing_phones:
                skipped += 1
                continue
            existing_phones.add(normalized)

            combined_tags: list[str] | None = None
            if row.tags or merged_tags:
                combined_tags = sorted(
                    {*(row.tags or []), *merged_tags}
                )

            combined_custom: dict | None = None
            if row.custom_fields or seg.custom_fields:
                combined_custom = {**seg.custom_fields, **(row.custom_fields or {})}

            rows_to_insert.append(
                Lead(
                    organization_id=organization_id,
                    lead_list_id=lead_list.id,
                    name=row.name.strip(),
                    email=row.email,
                    phone=row.phone.strip(),
                    phone_normalized=normalized,
                    company=row.company,
                    industry=row.industry or seg.industry,
                    location=row.location or seg.location,
                    source=payload.source,
                    tags=combined_tags,
                    custom_fields=combined_custom,
                )
            )

        try:
            inserted = LeadRepository.bulk_insert(db, rows_to_insert)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                409,
                "Insert failed due to a duplicate phone. "
                "Re-run the preview and retry.",
            ) from exc

        LeadListRepository.refresh_count(db, lead_list.id)
        db.commit()
        db.refresh(lead_list)

        return {
            "inserted": inserted,
            "skipped_duplicates": skipped,
            "lead_list": lead_list,
        }
