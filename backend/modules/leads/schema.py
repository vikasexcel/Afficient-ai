"""Request / response schemas for the leads API."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from modules.leads.model import ALL_LEAD_STATUSES


LeadStatus = str  # one of ALL_LEAD_STATUSES


# ---------------------------------------------------------------------------
# Phone validation helper (shared by create + update)
# ---------------------------------------------------------------------------

_PHONE_ALLOWED_RE = re.compile(r"^[+\d\s().\-]+$")


def _validate_phone(v: str) -> str:
    raw = (v or "").strip()
    if not raw:
        raise ValueError("phone is required")
    if not _PHONE_ALLOWED_RE.match(raw):
        raise ValueError("phone contains invalid characters")
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7:
        raise ValueError("phone is too short (need at least 7 digits)")
    if len(digits) > 15:
        raise ValueError("phone is too long (max 15 digits, E.164)")
    return raw


# ---------------------------------------------------------------------------
# Lead list
# ---------------------------------------------------------------------------


class LeadListOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None = None
    lead_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadListResponse(BaseModel):
    lead_lists: list[LeadListOut]


class CreateLeadListInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class UpdateLeadListInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Lead
# ---------------------------------------------------------------------------


class LeadOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    display_name: str | None = None
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str
    linkedin_url: str | None = None
    company: str | None = None
    job_title: str | None = None
    status: LeadStatus
    tags: list[str] | None = None
    extra_data: dict[str, Any] | None = None
    lead_list_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj, **kwargs):  # type: ignore[override]
        instance = super().model_validate(obj, **kwargs)
        # Populate lead_list_ids from the ORM relationship when available.
        try:
            instance.lead_list_ids = [ll.id for ll in obj.lead_lists]
        except Exception:
            pass
        return instance


class LeadListLeadsResponse(BaseModel):
    leads: list[LeadOut]
    total: int


class CreateLeadInput(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str = Field(min_length=1, max_length=40)
    linkedin_url: str | None = Field(default=None, max_length=500)
    company: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=120)
    status: str = "new"
    tags: list[str] | None = Field(default=None, max_length=50)
    extra_data: dict[str, Any] | None = None
    lead_list_ids: list[uuid.UUID] | None = None

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str | None) -> str | None:
        if not v:
            return None
        stripped = v.strip()
        return stripped or None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _validate_phone(v)

    @field_validator("first_name")
    @classmethod
    def _first_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("first_name is required")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in ALL_LEAD_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(ALL_LEAD_STATUSES)}"
            )
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 50:
            raise ValueError("tags list may not exceed 50 items")
        for tag in v:
            if len(tag) > 64:
                raise ValueError(
                    f"each tag must be 64 characters or fewer (got {len(tag)!r})"
                )
        return v

    @field_validator("extra_data")
    @classmethod
    def _extra_data_size(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        import json
        size = len(json.dumps(v))
        if size > 65536:  # 64 KB cap
            raise ValueError(
                f"extra_data payload too large ({size} bytes, max 65536)"
            )
        return v


class UpdateLeadInput(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    linkedin_url: str | None = Field(default=None, max_length=500)
    company: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=120)
    status: str | None = None
    tags: list[str] | None = None
    extra_data: dict[str, Any] | None = None

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str | None) -> str | None:
        if not v:
            return None
        stripped = v.strip()
        return stripped or None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_phone(v)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in ALL_LEAD_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(ALL_LEAD_STATUSES)}"
            )
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 50:
            raise ValueError("tags list may not exceed 50 items")
        for tag in v:
            if len(tag) > 64:
                raise ValueError(
                    f"each tag must be 64 characters or fewer"
                )
        return v

    @field_validator("extra_data")
    @classmethod
    def _extra_data_size(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        import json
        size = len(json.dumps(v))
        if size > 65536:
            raise ValueError(
                f"extra_data payload too large ({size} bytes, max 65536)"
            )
        return v


# ---------------------------------------------------------------------------
# Lead list membership
# ---------------------------------------------------------------------------


class AddLeadsToListInput(BaseModel):
    lead_ids: list[uuid.UUID] = Field(min_length=1)


class RemoveLeadsFromListInput(BaseModel):
    lead_ids: list[uuid.UUID] = Field(min_length=1)


class MembershipResponse(BaseModel):
    added: int = 0
    removed: int = 0
    already_member: int = 0
    not_member: int = 0
