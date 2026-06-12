"""FastAPI dependencies for the calendar module."""

from __future__ import annotations

from functools import lru_cache

from modules.calendar.service import CalendarService


@lru_cache(maxsize=1)
def get_calendar_service() -> CalendarService:
    """Return a singleton CalendarService (no Redis for now; can inject later)."""
    return CalendarService()
