"""Request / response schemas for the leads API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from modules.leads.model import ALL_LEAD_STATUSES


LeadStatus = Literal[
    "new", "contacted", "qualified", "converted", "lost"
]


# ---------------------------------------------------------------------------
# Lead list
# ---------------------------------------------------------------------------


class LeadListOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    source: str | None = None
    lead_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadListResponse(BaseModel):
    lead_lists: list[LeadListOut]


class CreateLeadListInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=120)


# ---------------------------------------------------------------------------
# Lead
# ---------------------------------------------------------------------------


class LeadOut(BaseModel):
    id: uuid.UUID
    lead_list_id: uuid.UUID | None
    name: str
    email: str | None
    phone: str
    company: str | None
    industry: str | None
    location: str | None
    source: str | None
    status: LeadStatus
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadListLeadsResponse(BaseModel):
    leads: list[LeadOut]
    total: int


class UpdateLeadInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    company: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    source: str | None = Field(default=None, max_length=120)
    status: LeadStatus | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    notes: str | None = None

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


# ---------------------------------------------------------------------------
# Upload preview + commit
# ---------------------------------------------------------------------------


class UploadParsedRow(BaseModel):
    """One CSV row after parsing + validation."""

    row_number: int
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    industry: str | None = None
    location: str | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None

    # Server-assigned classification.
    status: Literal["valid", "invalid", "duplicate"] = "valid"
    errors: list[str] = Field(default_factory=list)


class UploadPreviewResponse(BaseModel):
    """Result of ``POST /leads/upload/preview``.

    The frontend uses ``rows`` to render the data table, ``stats`` to
    drive summary chips, and ``detected_columns`` to confirm that header
    auto-mapping picked sensible columns.
    """

    rows: list[UploadParsedRow]
    detected_columns: dict[str, str | None]
    stats: dict[str, int]


class UploadSegmentation(BaseModel):
    """Bulk metadata applied to every row at commit time."""

    industry: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class CommitRowInput(BaseModel):
    """Row payload the FE sends after the user trims invalid + dupes."""

    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str = Field(min_length=4, max_length=40)
    company: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None


class CommitUploadInput(BaseModel):
    rows: list[CommitRowInput] = Field(min_length=1)
    segmentation: UploadSegmentation = Field(default_factory=UploadSegmentation)
    # Either pick an existing list or hand us a name so we'll create one.
    lead_list_id: uuid.UUID | None = None
    new_list_name: str | None = Field(default=None, max_length=120)
    source: str | None = Field(default=None, max_length=120)


class CommitUploadResponse(BaseModel):
    inserted: int
    skipped_duplicates: int
    lead_list: LeadListOut
