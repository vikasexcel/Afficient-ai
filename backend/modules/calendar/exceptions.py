"""Calendar module exceptions."""

from __future__ import annotations


class CalendarError(Exception):
    """Base error for all calendar operations."""

    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NoCalendarError(CalendarError):
    """No Google Calendar integration connected for this org."""

    def __init__(self, org_id: str | None = None) -> None:
        msg = (
            f"No Google Calendar connected for org {org_id}"
            if org_id
            else "No Google Calendar connected"
        )
        super().__init__(msg, status_code=404)


class SlotUnavailableError(CalendarError):
    """The requested time slot is busy."""

    def __init__(self, slot_iso: str | None = None) -> None:
        msg = f"Slot {slot_iso} is not available" if slot_iso else "Requested slot is not available"
        super().__init__(msg, status_code=409)


class CalendarAuthError(CalendarError):
    """OAuth token is invalid or revoked."""

    def __init__(self) -> None:
        super().__init__("Google Calendar auth token is invalid or expired. Please reconnect.", status_code=401)


class CalendarAPIError(CalendarError):
    """Google API returned an error."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Google Calendar API error: {detail}", status_code=502)
