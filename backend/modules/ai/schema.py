"""Request / response schemas for the AI module.

Two layers:

* **Wire schemas** (BaseModel) — used by the HTTP router and serialized
  to/from the client. Backwards-compatible by design.
* **Internal DTOs** (dataclass) — used by the orchestrator and service
  layer. Free to change without bumping API versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field



class MessageRole(str, Enum):
    """Standard chat roles. ``tool`` reserved for future function calling."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """A single message in a conversation, persisted in Redis + Postgres."""

    role: MessageRole
    content: str
    ts: datetime | None = None
    tokens: int | None = Field(
        default=None,
        description="Approx tokens (set by the provider where available).",
    )
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# /api/v1/ai/generate (stateless one-shot)
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    system: str | None = Field(default=None, max_length=8000)
    model: str | None = Field(default=None, max_length=64)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=4096)


class GenerateResponse(BaseModel):
    output: str
    model: str
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int


# ---------------------------------------------------------------------------
# /api/v1/ai/converse (stateful turn within a call)
# ---------------------------------------------------------------------------


class ConverseRequest(BaseModel):
    call_id: str = Field(
        min_length=1,
        max_length=128,
        description="Stable id for the call/session. Typically the LiveKit room name.",
    )
    user_input: str = Field(min_length=1, max_length=4000)
    persona: str | None = Field(
        default=None,
        max_length=64,
        description="Named system prompt (see modules.ai.prompts). Defaults to settings.AI_DEFAULT_PERSONA.",
    )
    qualification_framework: Literal["BANT", "MEDDICC"] | None = None
    persist_transcript: bool = True
    extra_context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Arbitrary call/lead metadata interpolated into the system prompt "
            "(e.g. {'lead_name': 'Jane', 'company': 'Acme'})."
        ),
    )


class ConverseResponse(BaseModel):
    call_id: str
    reply: str
    model: str
    finish_reason: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int
    history_length: int
    qualification: "QualificationSnapshot"


# ---------------------------------------------------------------------------
# Qualification (BANT / MEDDICC)
# ---------------------------------------------------------------------------


class QualificationSnapshot(BaseModel):
    framework: Literal["BANT", "MEDDICC"]
    status: Literal["not_started", "in_progress", "qualified", "disqualified"]
    score: int = Field(ge=0, le=100)
    answered_fields: list[str] = Field(default_factory=list)
    pending_fields: list[str] = Field(default_factory=list)
    fields: dict[str, str | None] = Field(default_factory=dict)
    last_updated: datetime | None = None


class QualificationGetResponse(BaseModel):
    call_id: str
    qualification: QualificationSnapshot


# ---------------------------------------------------------------------------
# Transcript + summary
# ---------------------------------------------------------------------------


class TranscriptEntry(BaseModel):
    role: MessageRole
    content: str
    ts: datetime
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class TranscriptResponse(BaseModel):
    call_id: str
    organization_id: str | None
    entries: list[TranscriptEntry]


class CallSummaryResponse(BaseModel):
    call_id: str
    summary: str | None
    qualification: QualificationSnapshot | None
    total_turns: int
    total_tokens: int
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime


class CallListEntry(BaseModel):
    """Compact row used by the Calls / Transcripts listings."""

    call_id: str
    persona: str | None
    framework: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    summary: str | None = None
    qualification_status: str | None = None
    qualification_score: int | None = None
    total_turns: int = 0
    total_tokens: int = 0


class CallListResponse(BaseModel):
    calls: list[CallListEntry]


# ---------------------------------------------------------------------------
# Internal DTOs
# ---------------------------------------------------------------------------


@dataclass
class ChatTurnStats:
    """Per-turn metrics captured by the OpenAI client."""

    latency_ms: int = 0
    ttft_ms: int = 0  # time to first token (streaming)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str | None = None
    model: str = ""


@dataclass
class ChatTurnResult:
    """What the LLM client returns after a (possibly streamed) turn."""

    text: str
    stats: ChatTurnStats = field(default_factory=ChatTurnStats)


# Pydantic forward-ref resolution
ConverseResponse.model_rebuild()
