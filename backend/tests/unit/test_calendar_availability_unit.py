"""Unit tests for calendar availability checking and free-slot logic.

Covers:
* _check_slot_sync / is_slot_available — free, busy, API error, auth error
* _fetch_free_slots_sync — normal day, full day, late-day timezone edge case,
  API error, invalid timezone
* _check_and_book_or_suggest (booking handler) — free slot books, busy slot
  surfaces alternatives, CalendarAPIError never becomes available=False
* _pick_and_confirm (booking handler) — free slot, no slots, API error

All external I/O is mocked; no real Google API, Redis, or Postgres calls.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from modules.ai.booking_handler import BookingHandler, BookingTurnResult
from modules.ai.booking_state import (
    PHASE_ASKING_TIME,
    PHASE_BOOKED,
    PHASE_CONFIRMING,
    PHASE_FAILED,
    PHASE_IDLE,
    PHASE_SUGGESTING,
    BookingMemory,
    BookingState,
)
from modules.calendar.exceptions import (
    CalendarAPIError,
    CalendarAuthError,
    NoCalendarError,
)
from modules.calendar.schema import BookedEvent, FreeSlot
from modules.calendar.service import CalendarService


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
CALL_ID = "avail-test-call"

_FUTURE_START = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)  # Saturday 10:00 UTC
_FREE_SLOT = FreeSlot(
    start=_FUTURE_START,
    end=_FUTURE_START + timedelta(minutes=30),
    start_display="Saturday, June 20 at 10:00 AM UTC",
    duration_minutes=30,
)
_BOOKED_EVENT = BookedEvent(
    event_id="evt_001",
    meet_link="https://meet.google.com/abc",
    html_link="https://calendar.google.com/e/abc",
    start_iso=_FUTURE_START.isoformat(),
    end_iso=(_FUTURE_START + timedelta(minutes=30)).isoformat(),
    start_display="Saturday, June 20 at 10:00 AM UTC",
    title="Meeting",
)


def _make_row(calendar_id: str = "primary") -> MagicMock:
    row = MagicMock()
    row.calendar_id = calendar_id
    row.access_token_enc = "enc_access"
    row.refresh_token_enc = "enc_refresh"
    row.token_expiry = None
    row.organization_id = ORG_ID
    row.calendar_email = "owner@example.com"
    return row


def _make_cal_service(*, redis=None) -> CalendarService:
    return CalendarService(redis_client=redis)


def _make_booking_state(**kwargs) -> BookingState:
    defaults = dict(
        phase=PHASE_ASKING_TIME,
        lead_email="lead@example.com",
        lead_name="Test Lead",
        org_id=str(ORG_ID),
        call_id=CALL_ID,
        timezone="UTC",
        duration_minutes=30,
    )
    defaults.update(kwargs)
    return BookingState(**defaults)


def _make_booking_handler(
    *,
    cal_svc: MagicMock | None = None,
    state: BookingState | None = None,
) -> tuple[BookingHandler, MagicMock, AsyncMock]:
    cal = cal_svc or MagicMock()
    mem = AsyncMock(spec=BookingMemory)
    mem.get = AsyncMock(return_value=state or _make_booking_state())
    mem.save = AsyncMock()
    openai = MagicMock()
    return BookingHandler(calendar_svc=cal, booking_memory=mem, openai_client=openai), cal, mem


# ---------------------------------------------------------------------------
# _check_slot_sync / is_slot_available
# ---------------------------------------------------------------------------


class TestCheckSlotSync:
    """Tests for _check_slot_sync (the sync Google API wrapper)."""

    def _setup(self, busy_periods: list) -> tuple[CalendarService, MagicMock]:
        """Return a CalendarService and a mock freebusy response."""
        svc = _make_cal_service()
        row = _make_row()

        fb_response = {
            "calendars": {
                "primary": {"busy": busy_periods}
            }
        }
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.return_value = fb_response

        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
        ):
            return svc, row

    def test_free_slot_returns_true(self):
        svc, row = self._setup(busy_periods=[])
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": []}}
        }
        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
        ):
            result = svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)
        assert result is True

    def test_busy_slot_returns_false(self):
        svc = _make_cal_service()
        row = _make_row()
        busy = [
            {
                "start": _FUTURE_START.isoformat(),
                "end": (_FUTURE_START + timedelta(hours=1)).isoformat(),
            }
        ]
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": busy}}
        }
        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
        ):
            result = svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)
        assert result is False

    def test_api_error_raises_calendar_api_error(self):
        svc = _make_cal_service()
        row = _make_row()
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.side_effect = Exception("503 Service Unavailable")
        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
        ):
            with pytest.raises(CalendarAPIError) as exc_info:
                svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)
        assert "503" in str(exc_info.value)

    def test_missing_calendar_key_in_response_treated_as_free(self):
        """If Google returns an unexpected structure (e.g. key mismatch), the
        slot is treated as available — absence of busy data ≠ busy."""
        svc = _make_cal_service()
        row = _make_row()
        mock_google_svc = MagicMock()
        # Response does not contain the calendar key at all
        mock_google_svc.freebusy().query().execute.return_value = {"calendars": {}}
        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
        ):
            result = svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)
        assert result is True  # empty busy list → available

    def test_build_service_failure_raises_calendar_api_error(self):
        """A failure in _build_service must propagate as CalendarAPIError, not bare Exception."""
        svc = _make_cal_service()
        row = _make_row()
        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", side_effect=RuntimeError("discovery failed")),
        ):
            with pytest.raises(CalendarAPIError):
                svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)


# ---------------------------------------------------------------------------
# _fetch_free_slots_sync — slot-finding logic
# ---------------------------------------------------------------------------


class TestFetchFreeSlotsSyncLogic:
    """Unit tests for _fetch_free_slots_sync without hitting the Google API."""

    def _run(
        self,
        *,
        busy_periods: list,
        target_date: date,
        tz_name: str = "UTC",
        duration_minutes: int = 30,
        count: int = 3,
        now_override: datetime | None = None,
        calendar_id: str = "primary",
    ) -> list[FreeSlot]:
        svc = _make_cal_service()
        row = _make_row(calendar_id=calendar_id)

        fb_response = {
            "calendars": {calendar_id: {"busy": busy_periods}}
        }
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.return_value = fb_response

        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
        ):
            if now_override:
                with patch("modules.calendar.service._utcnow", return_value=now_override):
                    return svc._fetch_free_slots_sync(
                        row,
                        target_date=target_date,
                        duration_minutes=duration_minutes,
                        tz_name=tz_name,
                        count=count,
                    )
            return svc._fetch_free_slots_sync(
                row,
                target_date=target_date,
                duration_minutes=duration_minutes,
                tz_name=tz_name,
                count=count,
            )

    def test_empty_calendar_returns_slots(self):
        """An empty calendar on a future date should return the requested number of slots."""
        target = date(2026, 6, 20)  # Saturday, no recurring events
        now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)  # the day before
        slots = self._run(busy_periods=[], target_date=target, now_override=now)
        assert len(slots) == 3
        # All slots must be within the 09:00–18:00 UTC window
        for s in slots:
            assert s.start.hour >= 9
            assert s.end.hour <= 18

    def test_busy_all_day_returns_no_slots(self):
        """A day-long event should block all slots."""
        target = date(2026, 6, 20)
        now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
        busy = [
            {
                "start": "2026-06-20T09:00:00+00:00",
                "end": "2026-06-20T18:00:00+00:00",
            }
        ]
        slots = self._run(busy_periods=busy, target_date=target, now_override=now)
        assert slots == []

    def test_busy_morning_returns_afternoon_slots(self):
        """Blocks in the morning should leave afternoon slots."""
        target = date(2026, 6, 20)
        now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
        busy = [
            {"start": "2026-06-20T09:00:00+00:00", "end": "2026-06-20T13:00:00+00:00"}
        ]
        slots = self._run(busy_periods=busy, target_date=target, count=3, now_override=now)
        assert len(slots) > 0
        for s in slots:
            # All free slots must start at or after 13:00 UTC
            assert s.start >= datetime(2026, 6, 20, 13, 0, tzinfo=timezone.utc)

    def test_past_time_filter_removes_elapsed_slots(self):
        """Slots before 'now' must not be offered."""
        target = date(2026, 6, 20)
        # It is currently 14:00 UTC on the target date
        now = datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)
        slots = self._run(busy_periods=[], target_date=target, now_override=now)
        for s in slots:
            assert s.start >= now

    def test_workday_over_returns_empty_list(self):
        """When 'now' is at or after 18:00 on the target date, no slots are returned."""
        target = date(2026, 6, 20)
        now = datetime(2026, 6, 20, 18, 0, tzinfo=timezone.utc)  # exactly end of day
        slots = self._run(busy_periods=[], target_date=target, now_override=now)
        assert slots == []

    def test_late_afternoon_returns_one_slot(self):
        """At 17:29 UTC there is exactly one valid 30-min slot (17:30–18:00)."""
        target = date(2026, 6, 20)
        now = datetime(2026, 6, 20, 17, 29, tzinfo=timezone.utc)
        slots = self._run(busy_periods=[], target_date=target, count=3, now_override=now)
        assert len(slots) == 1
        assert slots[0].start == datetime(2026, 6, 20, 17, 30, tzinfo=timezone.utc)

    def test_17_30_now_returns_no_slots(self):
        """Exactly at 17:30 there is no room for a 30-min slot before 18:00."""
        target = date(2026, 6, 20)
        now = datetime(2026, 6, 20, 17, 30, tzinfo=timezone.utc)
        slots = self._run(busy_periods=[], target_date=target, count=3, now_override=now)
        assert slots == []

    def test_timezone_ist_window_uses_ist_hours(self):
        """With IST timezone, the 09:00–18:00 window is in IST, not UTC."""
        target = date(2026, 6, 20)
        # 00:00 UTC = 05:30 IST → well before IST 09:00, no past-time push
        now = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
        slots = self._run(
            busy_periods=[],
            target_date=target,
            tz_name="Asia/Kolkata",
            now_override=now,
        )
        assert len(slots) == 3
        # Slot starts must be in IST 09:00–18:00 range
        # IST = UTC+5:30, so IST 09:00 = UTC 03:30
        utc_window_start = datetime(2026, 6, 20, 3, 30, tzinfo=timezone.utc)
        utc_window_end = datetime(2026, 6, 20, 12, 30, tzinfo=timezone.utc)
        for s in slots:
            assert s.start >= utc_window_start
            assert s.end <= utc_window_end

    def test_invalid_timezone_falls_back_to_utc(self):
        """An unrecognised timezone string must silently fall back to UTC."""
        target = date(2026, 6, 20)
        now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
        slots = self._run(
            busy_periods=[],
            target_date=target,
            tz_name="Mars/Olympus_Mons",
            now_override=now,
        )
        # Should still return slots (using UTC fallback)
        assert len(slots) > 0

    def test_api_error_propagates_as_calendar_api_error(self):
        """When the Google API call fails, CalendarAPIError must bubble up."""
        svc = _make_cal_service()
        row = _make_row()
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.side_effect = RuntimeError("quota exceeded")
        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
            patch("modules.calendar.service._utcnow",
                  return_value=datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)),
        ):
            with pytest.raises(CalendarAPIError, match="quota exceeded"):
                svc._fetch_free_slots_sync(
                    row,
                    target_date=date(2026, 6, 20),
                    duration_minutes=30,
                    tz_name="UTC",
                    count=3,
                )

    def test_respects_count_limit(self):
        """No more than `count` slots are returned."""
        target = date(2026, 6, 20)
        now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
        slots = self._run(busy_periods=[], target_date=target, count=2, now_override=now)
        assert len(slots) <= 2


# ---------------------------------------------------------------------------
# BookingHandler._check_and_book_or_suggest — the core fix
# ---------------------------------------------------------------------------


class TestCheckAndBookOrSuggest:
    """The critical invariant: a CalendarAPIError must NEVER set available=False."""

    @pytest.mark.asyncio
    async def test_free_slot_proceeds_to_booking(self):
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=True)
        cal.book_meeting = AsyncMock(return_value=_BOOKED_EVENT)

        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with (
            patch("modules.ai.booking_handler.SessionLocal"),
            patch.object(handler, "_send_confirmation", AsyncMock()),
            patch("modules.ai.booking_handler.asyncio.create_task"),
        ):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.meeting_booked
        assert result.consumed
        cal.book_meeting.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_busy_slot_offers_alternatives(self):
        alt_slot = FreeSlot(
            start=_FUTURE_START + timedelta(hours=1),
            end=_FUTURE_START + timedelta(hours=1, minutes=30),
            start_display="Saturday at 11:00 AM",
            duration_minutes=30,
        )
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=False)
        cal.get_free_slots = AsyncMock(return_value=[alt_slot])

        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.consumed
        assert not result.meeting_booked
        assert "taken" in (result.speak_override or "").lower()
        # State is mutated in-place by _check_and_book_or_suggest
        assert state.phase == PHASE_SUGGESTING

    @pytest.mark.asyncio
    async def test_calendar_api_error_never_marks_slot_busy(self):
        """Core regression test: CalendarAPIError must surface as an error,
        not silently treat the slot as occupied."""
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(
            side_effect=CalendarAPIError("503 Service Unavailable")
        )
        cal.book_meeting = AsyncMock()  # must NOT be called

        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        # The slot must not be treated as "taken"
        assert result.consumed
        assert result.speak_override is not None
        speak = result.speak_override.lower()
        assert "taken" not in speak, "CalendarAPIError was misreported as a busy slot"
        assert "booked" not in speak or "team" in speak  # error message, not busy message

        # booking must not have been attempted
        cal.book_meeting.assert_not_awaited()

        # Phase must be FAILED, not SUGGESTING (alternatives)
        assert state.phase == PHASE_FAILED

    @pytest.mark.asyncio
    async def test_calendar_auth_error_fails_gracefully(self):
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(side_effect=CalendarAuthError())
        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.consumed
        assert state.phase == PHASE_FAILED

    @pytest.mark.asyncio
    async def test_no_calendar_error_fails_gracefully(self):
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(side_effect=NoCalendarError())
        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.consumed
        assert state.phase == PHASE_FAILED

    @pytest.mark.asyncio
    async def test_busy_slot_with_api_error_on_alternatives_fails_gracefully(self):
        """When the slot is busy AND the alternatives lookup also fails with
        CalendarAPIError, the caller must get a proper error, not silence."""
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=False)  # slot is genuinely busy
        cal.get_free_slots = AsyncMock(
            side_effect=CalendarAPIError("rate limited")
        )
        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.consumed
        assert state.phase == PHASE_FAILED

    @pytest.mark.asyncio
    async def test_busy_slot_with_empty_alternatives_asks_for_different_day(self):
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=False)
        cal.get_free_slots = AsyncMock(return_value=[])

        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.consumed
        assert "day" in (result.speak_override or "").lower()
        assert state.phase == PHASE_ASKING_TIME


# ---------------------------------------------------------------------------
# BookingHandler._pick_and_confirm
# ---------------------------------------------------------------------------


class TestPickAndConfirm:
    @pytest.mark.asyncio
    async def test_free_slot_offered_for_confirmation(self):
        cal = MagicMock()
        cal.get_free_slots = AsyncMock(return_value=[_FREE_SLOT])

        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._pick_and_confirm(state)

        assert result.consumed
        assert "opening" in (result.speak_override or "").lower()
        assert state.phase == PHASE_CONFIRMING

    @pytest.mark.asyncio
    async def test_no_free_slots_asks_for_different_day(self):
        cal = MagicMock()
        cal.get_free_slots = AsyncMock(return_value=[])

        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._pick_and_confirm(state)

        assert result.consumed
        assert "day" in (result.speak_override or "").lower()
        assert state.phase == PHASE_ASKING_TIME

    @pytest.mark.asyncio
    async def test_calendar_api_error_fails_with_spoken_error(self):
        """CalendarAPIError during slot lookup must surface as an error message,
        not be swallowed and treated as 'no slots today'."""
        cal = MagicMock()
        cal.get_free_slots = AsyncMock(
            side_effect=CalendarAPIError("Google API: 500 Internal Server Error")
        )
        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._pick_and_confirm(state)

        assert result.consumed
        # Must not say "no openings today" — that implies no free slots, not an API error
        speak = (result.speak_override or "").lower()
        assert "openings today" not in speak, (
            "CalendarAPIError was misreported as 'no slots today'"
        )
        assert state.phase == PHASE_FAILED

    @pytest.mark.asyncio
    async def test_calendar_auth_error_transitions_to_failed(self):
        cal = MagicMock()
        cal.get_free_slots = AsyncMock(side_effect=CalendarAuthError())
        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._pick_and_confirm(state)

        assert result.consumed
        assert state.phase == PHASE_FAILED

    @pytest.mark.asyncio
    async def test_no_calendar_error_transitions_to_failed(self):
        cal = MagicMock()
        cal.get_free_slots = AsyncMock(side_effect=NoCalendarError())
        state = _make_booking_state()
        handler, _, _ = _make_booking_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._pick_and_confirm(state)

        assert result.consumed
        assert state.phase == PHASE_FAILED
