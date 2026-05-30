"""Request / response schemas for the playbook API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from modules.playbook.model import (
    ALL_PLAYBOOK_FRAMEWORKS,
    ALL_PLAYBOOK_STATUSES,
)


PlaybookStatus = Literal["draft", "active", "archived"]
PlaybookFramework = Literal["BANT", "MEDDICC", "CUSTOM"]


# ---------------------------------------------------------------------------
# Field DTOs
# ---------------------------------------------------------------------------


class PlaybookFieldInput(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    weight: int = Field(default=1, ge=1, le=10)
    required: bool = False
    cue_patterns: list[str] = Field(default_factory=list)
    position: int = Field(default=0, ge=0)

    @field_validator("key")
    @classmethod
    def _key_slug(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "_")
        if not v.replace("_", "").isalnum():
            raise ValueError(
                "key must be alphanumeric with optional underscores"
            )
        return v


class PlaybookFieldOut(PlaybookFieldInput):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class CreatePlaybookInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    framework: PlaybookFramework = "BANT"
    persona_name: str = Field(default="outbound_sdr", max_length=64)
    system_prompt: str | None = Field(default=None, max_length=8000)
    opening_line: str | None = Field(default=None, max_length=2000)
    default_objective: str | None = Field(default=None, max_length=255)
    voice_id: str | None = Field(default=None, max_length=64)
    default_context: dict[str, Any] | None = None
    disqualifying_patterns: list[str] = Field(default_factory=list)
    fields: list[PlaybookFieldInput] = Field(default_factory=list)

    @field_validator("framework")
    @classmethod
    def _framework(cls, v: str) -> str:
        if v not in ALL_PLAYBOOK_FRAMEWORKS:
            raise ValueError(f"framework must be one of {sorted(ALL_PLAYBOOK_FRAMEWORKS)}")
        return v


class UpdatePlaybookInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    framework: PlaybookFramework | None = None
    persona_name: str | None = Field(default=None, max_length=64)
    system_prompt: str | None = Field(default=None, max_length=8000)
    opening_line: str | None = Field(default=None, max_length=2000)
    default_objective: str | None = Field(default=None, max_length=255)
    voice_id: str | None = Field(default=None, max_length=64)
    default_context: dict[str, Any] | None = None
    disqualifying_patterns: list[str] | None = None
    fields: list[PlaybookFieldInput] | None = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class PlaybookSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: PlaybookStatus
    framework: PlaybookFramework
    persona_name: str
    version: int
    field_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlaybookDetail(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    status: PlaybookStatus
    framework: PlaybookFramework
    persona_name: str
    system_prompt: str | None
    opening_line: str | None
    default_objective: str | None
    voice_id: str | None
    default_context: dict[str, Any] | None
    disqualifying_patterns: list[str] | None
    version: int
    fields: list[PlaybookFieldOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlaybookListResponse(BaseModel):
    playbooks: list[PlaybookSummary]


class PlaybookVersionOut(BaseModel):
    id: uuid.UUID
    playbook_id: uuid.UUID
    version: int
    payload: dict[str, Any]
    created_at: datetime
    created_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class PlaybookVersionListResponse(BaseModel):
    versions: list[PlaybookVersionOut]


# ---------------------------------------------------------------------------
# Test / dry-run
# ---------------------------------------------------------------------------


class PlaybookTestInput(BaseModel):
    """Simulate a user turn against the playbook's qualification cues."""

    user_text: str = Field(min_length=1, max_length=4000)
    extra_context: dict[str, Any] | None = None


class PlaybookTestResponse(BaseModel):
    rendered_system_prompt: str
    qualification_before: dict[str, Any]
    qualification_after: dict[str, Any]
    newly_set_fields: list[str]


class PlaybookPromptPreview(BaseModel):
    rendered_system_prompt: str
    placeholders: list[str]
