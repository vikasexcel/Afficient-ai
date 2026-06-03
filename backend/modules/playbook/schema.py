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
from modules.playbook.objections import ALL_OBJECTION_TYPES
from modules.tts.voice_registry import (
    ALL_GENDERS,
    SUPPORTED_VOICE_PROVIDERS,
)


PlaybookStatus = Literal["draft", "active", "archived"]
PlaybookFramework = Literal["BANT", "MEDDICC", "CUSTOM"]


def _validate_voice_provider(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip().lower()
    if not v:
        return None
    if v not in SUPPORTED_VOICE_PROVIDERS:
        raise ValueError(
            "voice_provider must be one of "
            f"{sorted(SUPPORTED_VOICE_PROVIDERS)}"
        )
    return v


def _normalize_agent_name(v: str | None) -> str | None:
    """Treat blank agent names as unset so backward-compat fallback applies."""

    if v is None:
        return v
    v = v.strip()
    return v or None


def _validate_voice_gender(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip().lower()
    if not v:
        return None
    if v not in ALL_GENDERS:
        raise ValueError(f"voice_gender must be one of {sorted(ALL_GENDERS)}")
    return v


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


class PlaybookBranchInput(BaseModel):
    """One dynamic branching rule (stored as JSON on the playbook)."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    priority: int = Field(default=100, ge=0, le=1000)
    once: bool = True
    when: dict[str, Any] = Field(default_factory=dict)
    then: dict[str, Any] = Field(default_factory=dict)

    @field_validator("when")
    @classmethod
    def _validate_when(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Reject unsupported condition keys at API time.

        Without this, a typo (or an aspirational key like ``any_keyword``)
        silently became an always-true branch.
        """
        # Import lazily to avoid circular import (branches imports
        # qualification, which lives in modules.ai).
        from modules.playbook.branches import _ALLOWED_WHEN_KEYS

        unknown = set(v.keys()) - _ALLOWED_WHEN_KEYS
        if unknown:
            raise ValueError(
                "unknown branch condition keys: "
                + ", ".join(sorted(unknown))
                + f" (allowed: {sorted(_ALLOWED_WHEN_KEYS)})"
            )
        return v


class PlaybookObjectionInput(BaseModel):
    """One objection-handling rule (stored as JSON on the playbook)."""

    objection_type: str = Field(default="custom", max_length=48)
    objection_trigger: str = Field(default="", max_length=300)
    objection_response: str = Field(min_length=1, max_length=1000)
    fallback_response: str | None = Field(default=None, max_length=1000)

    @field_validator("objection_type")
    @classmethod
    def _objection_type(cls, v: str) -> str:
        v = (v or "custom").strip().lower()
        if v not in ALL_OBJECTION_TYPES:
            raise ValueError(
                f"objection_type must be one of {sorted(ALL_OBJECTION_TYPES)}"
            )
        return v

    @field_validator("objection_trigger", "objection_response")
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class CreatePlaybookInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    framework: PlaybookFramework = "BANT"
    persona_name: str = Field(default="outbound_sdr", max_length=64)
    agent_name: str | None = Field(default=None, min_length=2, max_length=50)
    system_prompt: str | None = Field(default=None, max_length=8000)
    opening_line: str | None = Field(default=None, max_length=2000)
    default_objective: str | None = Field(default=None, max_length=255)
    voice_provider: str | None = Field(default=None, max_length=32)
    voice_id: str | None = Field(default=None, max_length=64)
    voice_name: str | None = Field(default=None, max_length=120)
    voice_gender: str | None = Field(default=None, max_length=16)
    voice_accent: str | None = Field(default=None, max_length=32)
    voice_language: str | None = Field(default=None, max_length=16)
    company_name: str | None = Field(default=None, max_length=120)
    company_intro: str | None = Field(default=None, max_length=1000)
    company_description: str | None = Field(default=None, max_length=2000)
    value_proposition: str | None = Field(default=None, max_length=1000)
    default_context: dict[str, Any] | None = None
    disqualifying_patterns: list[str] = Field(default_factory=list)
    fields: list[PlaybookFieldInput] = Field(default_factory=list)
    branches: list[PlaybookBranchInput] = Field(default_factory=list)
    objections: list[PlaybookObjectionInput] = Field(default_factory=list)

    @field_validator("agent_name", mode="before")
    @classmethod
    def _agent_name(cls, v: str | None) -> str | None:
        return _normalize_agent_name(v)

    @field_validator("framework")
    @classmethod
    def _framework(cls, v: str) -> str:
        if v not in ALL_PLAYBOOK_FRAMEWORKS:
            raise ValueError(f"framework must be one of {sorted(ALL_PLAYBOOK_FRAMEWORKS)}")
        return v

    @field_validator("voice_provider")
    @classmethod
    def _voice_provider(cls, v: str | None) -> str | None:
        return _validate_voice_provider(v)

    @field_validator("voice_gender")
    @classmethod
    def _voice_gender(cls, v: str | None) -> str | None:
        return _validate_voice_gender(v)


class UpdatePlaybookInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    framework: PlaybookFramework | None = None
    persona_name: str | None = Field(default=None, max_length=64)
    agent_name: str | None = Field(default=None, min_length=2, max_length=50)
    system_prompt: str | None = Field(default=None, max_length=8000)
    opening_line: str | None = Field(default=None, max_length=2000)
    default_objective: str | None = Field(default=None, max_length=255)
    voice_provider: str | None = Field(default=None, max_length=32)
    voice_id: str | None = Field(default=None, max_length=64)
    voice_name: str | None = Field(default=None, max_length=120)
    voice_gender: str | None = Field(default=None, max_length=16)
    voice_accent: str | None = Field(default=None, max_length=32)
    voice_language: str | None = Field(default=None, max_length=16)
    company_name: str | None = Field(default=None, max_length=120)
    company_intro: str | None = Field(default=None, max_length=1000)
    company_description: str | None = Field(default=None, max_length=2000)
    value_proposition: str | None = Field(default=None, max_length=1000)
    default_context: dict[str, Any] | None = None
    disqualifying_patterns: list[str] | None = None
    fields: list[PlaybookFieldInput] | None = None
    branches: list[PlaybookBranchInput] | None = None
    objections: list[PlaybookObjectionInput] | None = None

    @field_validator("agent_name", mode="before")
    @classmethod
    def _agent_name(cls, v: str | None) -> str | None:
        return _normalize_agent_name(v)

    @field_validator("voice_provider")
    @classmethod
    def _voice_provider(cls, v: str | None) -> str | None:
        return _validate_voice_provider(v)

    @field_validator("voice_gender")
    @classmethod
    def _voice_gender(cls, v: str | None) -> str | None:
        return _validate_voice_gender(v)


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
    agent_name: str | None
    system_prompt: str | None
    opening_line: str | None
    default_objective: str | None
    voice_provider: str | None
    voice_id: str | None
    voice_name: str | None
    voice_gender: str | None
    voice_accent: str | None
    voice_language: str | None
    company_name: str | None
    company_intro: str | None
    company_description: str | None
    value_proposition: str | None
    default_context: dict[str, Any] | None
    disqualifying_patterns: list[str] | None
    branches: list[dict[str, Any]] | None = None
    objections: list[dict[str, Any]] | None = None
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


class ObjectionMatchOut(BaseModel):
    objection_type: str
    objection_trigger: str
    objection_response: str
    fallback_response: str | None = None
    score: float
    strategy: str


class PlaybookTestResponse(BaseModel):
    rendered_system_prompt: str
    qualification_before: dict[str, Any]
    qualification_after: dict[str, Any]
    newly_set_fields: list[str]
    branches_fired: list[str] = Field(default_factory=list)
    objection_matched: ObjectionMatchOut | None = None


class PlaybookPromptPreview(BaseModel):
    rendered_system_prompt: str
    placeholders: list[str]
