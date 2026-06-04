"""Request / response schemas for the campaigns API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from modules.campaign.model import ALL_CAMPAIGN_STATUSES


# ---------------------------------------------------------------------------
# Sub-objects (mirror the frontend campaign draft shape)
# ---------------------------------------------------------------------------


class CampaignSchedule(BaseModel):
    """When the campaign should start dialing.

    The frontend collects a local ``date`` + ``time`` + IANA ``timezone``.
    The service converts that to a UTC ``scheduled_at`` for storage.
    """

    start_immediately: bool = True
    date: str | None = None  # "YYYY-MM-DD"
    time: str | None = None  # "HH:mm"
    timezone: str | None = None


class CampaignBusinessHours(BaseModel):
    days: list[str] = Field(default_factory=list)
    start: str = "09:00"
    end: str = "17:00"
    skip_holidays: bool = False


class CampaignRetryConfig(BaseModel):
    """Retry policy consumed by the Retry Execution Engine.

    ``retry_interval_minutes`` + ``backoff_strategy`` are the canonical fields.
    ``backoff_minutes`` is kept (optional) for backward compatibility with
    campaigns persisted before the engine existed; when ``retry_interval_minutes``
    is omitted the engine falls back to it.
    """

    max_attempts: int = Field(default=5, ge=1, le=10)
    retry_interval_minutes: int = Field(default=15, ge=0)
    backoff_strategy: Literal["fixed", "exponential"] = "fixed"

    # Legacy / optional knobs.
    backoff_minutes: int | None = Field(default=None, ge=0)
    retry_on: list[str] | None = None


class CampaignPacing(BaseModel):
    """Throttle how fast the scheduler dials a campaign's leads.

    ``0`` on either field disables that specific limit (unlimited).
    """

    calls_per_hour: int = Field(default=60, ge=0, le=100000)
    max_concurrent_calls: int = Field(default=5, ge=0, le=10000)


class CampaignVoicemailConfig(BaseModel):
    """Answering Machine Detection (AMD) + Voicemail Drop settings.

    When ``voicemail_enabled`` the telephony layer asks the provider to run
    AMD; on a detected voicemail it plays ``voicemail_message_url`` instead of
    running the AI conversation. ``retry_on_voicemail`` decides whether a
    voicemail outcome is retried by the campaign retry engine or marked
    completed. ``amd_unknown_fallback`` chooses the behaviour when detection is
    inconclusive (default: continue the conversation as if human).
    """

    voicemail_enabled: bool = False
    voicemail_message_url: str | None = Field(default=None, max_length=2000)
    retry_on_voicemail: bool = False
    amd_unknown_fallback: Literal["human", "voicemail"] = "human"

    @field_validator("voicemail_message_url")
    @classmethod
    def _v_url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError(
                "voicemail_message_url must be an http(s) URL"
            )
        return v


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class CreateCampaign(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    playbook_id: uuid.UUID | None = None
    lead_list_id: uuid.UUID | None = None
    schedule: CampaignSchedule | None = None
    business_hours: CampaignBusinessHours | None = None
    retry_config: CampaignRetryConfig | None = None
    pacing: CampaignPacing | None = None
    voicemail_config: CampaignVoicemailConfig | None = None
    # When true the service flips status to ``scheduled``/``active`` based on
    # the schedule instead of leaving the campaign as a ``draft``.
    launch: bool = False


class UpdateCampaign(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    playbook_id: uuid.UUID | None = None
    lead_list_id: uuid.UUID | None = None
    schedule: CampaignSchedule | None = None
    business_hours: CampaignBusinessHours | None = None
    retry_config: CampaignRetryConfig | None = None
    pacing: CampaignPacing | None = None
    voicemail_config: CampaignVoicemailConfig | None = None
    status: str | None = None


class ActivateCampaign(BaseModel):
    campaign_id: str


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    playbook_id: uuid.UUID | None = None
    lead_list_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    timezone: str | None = None
    business_hours: dict | None = None
    retry_config: dict | None = None
    voicemail_config: dict | None = None
    calls_per_hour: int | None = None
    max_concurrent_calls: int | None = None
    created_at: datetime
    updated_at: datetime

    # Enriched, read-only convenience fields for the listing UI.
    playbook_name: str | None = None
    lead_list_name: str | None = None
    lead_count: int | None = None

    model_config = {"from_attributes": True}


class CampaignListResponse(BaseModel):
    campaigns: list[CampaignOut]
    total: int


def is_valid_status(status: str) -> bool:
    return status in ALL_CAMPAIGN_STATUSES
