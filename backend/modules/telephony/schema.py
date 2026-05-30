"""Pydantic request / response schemas for the telephony module."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _validate_e164(v: str) -> str:
    v = (v or "").strip()
    if not _E164_RE.match(v):
        raise ValueError(
            "phone number must be E.164 (e.g. +14155551234)"
        )
    return v


# ---------------------------------------------------------------------------
# Outbound call requests
# ---------------------------------------------------------------------------


class InitiateCallRequest(BaseModel):
    """Body for ``POST /telephony/calls``."""

    to_number: str = Field(description="Destination in E.164")
    from_number: str | None = Field(
        default=None,
        description="Override caller ID (defaults to TWILIO_PHONE_NUMBER)",
    )

    # Optional lead / campaign linkage.
    lead_id: uuid.UUID | None = None
    lead_name: str | None = Field(default=None, max_length=255)
    lead_phone: str | None = None
    campaign_id: uuid.UUID | None = None

    # Agent / conversation knobs forwarded to the orchestrator.
    playbook_id: uuid.UUID | None = None
    persona: str | None = Field(default=None, max_length=64)
    qualification_framework: str | None = Field(default=None, max_length=16)
    opening_line: str | None = Field(default=None, max_length=2000)
    extra_context: dict[str, Any] | None = None

    # Twilio knobs
    record: bool | None = None
    dial_timeout_seconds: int | None = Field(default=None, ge=5, le=120)
    answering_machine_detection: bool = False

    # Pre-populate this if the caller wants to reuse a known room name.
    room_name: str | None = Field(default=None, max_length=128)

    @field_validator("to_number")
    @classmethod
    def _v_to(cls, v: str) -> str:
        return _validate_e164(v)

    @field_validator("from_number")
    @classmethod
    def _v_from(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_e164(v)

    @field_validator("lead_phone")
    @classmethod
    def _v_lead(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_e164(v)


# ---------------------------------------------------------------------------
# Call responses
# ---------------------------------------------------------------------------


class CallResponse(BaseModel):
    id: uuid.UUID
    call_sid: str | None = None
    room_name: str
    direction: str
    status: str
    from_number: str
    to_number: str
    lead_id: uuid.UUID | None = None
    lead_name: str | None = None
    lead_phone: str | None = None
    campaign_id: uuid.UUID | None = None
    queued_at: datetime
    initiated_at: datetime | None = None
    ringing_at: datetime | None = None
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    price: float | None = None
    price_unit: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    extra: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CallListResponse(BaseModel):
    calls: list[CallResponse]


# ---------------------------------------------------------------------------
# Call events (read API for debugging UIs)
# ---------------------------------------------------------------------------


class CallEventResponse(BaseModel):
    id: uuid.UUID
    call_sid: str | None = None
    event_type: str
    source: str
    payload: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CallEventListResponse(BaseModel):
    events: list[CallEventResponse]


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


class RetryCallResponse(BaseModel):
    original_call_id: uuid.UUID
    new_call: CallResponse


# ---------------------------------------------------------------------------
# Webhook acknowledgement (we always reply with TwiML XML in the router,
# but the JSON status webhook handler returns this shape for clients
# that pass ``Accept: application/json``).
# ---------------------------------------------------------------------------


class WebhookAck(BaseModel):
    ok: bool = True
    call_sid: str | None = None
    status: str | None = None
