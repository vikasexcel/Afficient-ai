"""Pydantic schemas for the calendar module."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel


class CalendarIntegrationOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    provider: str
    calendar_email: Optional[str] = None
    calendar_id: str
    connected: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class FreeSlot(BaseModel):
    start: datetime
    end: datetime
    start_display: str  # "Tomorrow at 3:00 PM IST"
    duration_minutes: int


class AvailabilityRequest(BaseModel):
    date_iso: str          # "2026-06-12" — the requested date
    timezone: str = "UTC"  # IANA timezone, e.g. "Asia/Kolkata"
    duration_minutes: int = 30
    count: int = 3         # How many slots to return


class AvailabilityResponse(BaseModel):
    slots: list[FreeSlot]
    date_display: str       # "Tomorrow, June 12"


class BookingRequest(BaseModel):
    slot_start_iso: str         # ISO8601 UTC string
    duration_minutes: int = 30
    title: str = "Meeting"
    description: str = ""
    attendee_email: str
    attendee_name: str
    timezone: str = "UTC"


class BookedEvent(BaseModel):
    event_id: str
    meet_link: Optional[str] = None
    html_link: str
    start_iso: str
    end_iso: str
    start_display: str
    title: str
