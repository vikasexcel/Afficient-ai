"""Tests for the deep-fix of the Google Calendar booking system.

Covers every issue identified in the audit:
1.  calendar_id stored as "primary" → real calendar ID fetched during OAuth
2.  upsert_integration updates calendar_id on reconnect
3.  FreeBusy response key mismatch detection & logging
4.  alternatives error handling no longer silently returns []
5.  timezone-aware today_iso in extract_slot_preference
6.  Slot free / busy with real calendar ID (email, not "primary")
7.  Calendar API failure surfaces correctly
8.  OAuth reconnect updates the stored calendar_id
9.  Timezone conversion across multiple zones

All external I/O (Google API, Redis, Postgres, SMTP) is mocked.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from modules.ai.booking_handler import (
    BookingHandler,
    BookingTurnResult,
    _today_in_timezone,
)
from modules.ai.booking_intents import SlotPreference
from modules.ai.booking_state import (
    PHASE_ASKING_TIME,
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
# Shared constants
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
CALL_ID = "fix-test-call"
REAL_CAL_ID = "owner@company.com"  # resolved email, not "primary"

_FUTURE_START = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
_BOOKED_EVENT = BookedEvent(
    event_id="evt_fix_001",
    meet_link="https://meet.google.com/fix",
    html_link="https://calendar.google.com/fix",
    start_iso=_FUTURE_START.isoformat(),
    end_iso=(_FUTURE_START + timedelta(minutes=30)).isoformat(),
    start_display="Tuesday, July 15 at 10:00 AM UTC",
    title="Meeting",
)
_ALT_SLOT = FreeSlot(
    start=_FUTURE_START + timedelta(hours=2),
    end=_FUTURE_START + timedelta(hours=2, minutes=30),
    start_display="Tuesday, July 15 at 12:00 PM UTC",
    duration_minutes=30,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(calendar_id: str = REAL_CAL_ID) -> MagicMock:
    row = MagicMock()
    row.calendar_id = calendar_id
    row.calendar_email = "owner@company.com"
    row.access_token_enc = "enc_a"
    row.refresh_token_enc = "enc_r"
    row.token_expiry = None
    row.organization_id = ORG_ID
    return row


def _make_state(**kwargs) -> BookingState:
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


def _make_handler(
    *,
    cal_svc: MagicMock | None = None,
    state: BookingState | None = None,
) -> tuple[BookingHandler, MagicMock, AsyncMock]:
    cal = cal_svc or MagicMock()
    mem = AsyncMock(spec=BookingMemory)
    mem.get = AsyncMock(return_value=state or _make_state())
    mem.save = AsyncMock()
    openai = MagicMock()
    return (
        BookingHandler(calendar_svc=cal, booking_memory=mem, openai_client=openai),
        cal,
        mem,
    )


# ---------------------------------------------------------------------------
# Issue 1 & 2: calendar_id resolution during OAuth + reconnect
# ---------------------------------------------------------------------------


class TestUpsertIntegrationCalendarId:
    """upsert_integration must persist a real calendar_id and update it on reconnect."""

    def _make_db(self) -> MagicMock:
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        return db

    def test_new_row_stores_real_calendar_id(self):
        from modules.calendar.service import CalendarService
        from modules.calendar.encryption import encrypt_token

        db = self._make_db()
        with (
            patch("modules.calendar.service.encrypt_token", side_effect=lambda t: f"enc:{t}"),
        ):
            row = CalendarService.upsert_integration(
                db,
                org_id=ORG_ID,
                access_token="tok",
                refresh_token="ref",
                token_expiry=None,
                calendar_email="user@gmail.com",
                calendar_id="user@gmail.com",
            )
        # The new row should be added and have the email as calendar_id
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.calendar_id == "user@gmail.com"

    def test_reconnect_updates_calendar_id_when_real_id_provided(self):
        """When re-connecting, calendar_id must be updated if a resolved ID is given."""
        from modules.calendar.service import CalendarService

        existing = MagicMock()
        existing.calendar_id = "primary"  # old value

        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = existing

        with patch("modules.calendar.service.encrypt_token", side_effect=lambda t: f"enc:{t}"):
            CalendarService.upsert_integration(
                db,
                org_id=ORG_ID,
                access_token="new_tok",
                refresh_token="new_ref",
                token_expiry=None,
                calendar_email="user@gmail.com",
                calendar_id="user@gmail.com",
            )

        assert existing.calendar_id == "user@gmail.com"

    def test_reconnect_does_not_overwrite_with_primary(self):
        """If only 'primary' is passed, the existing real calendar_id is preserved."""
        from modules.calendar.service import CalendarService

        existing = MagicMock()
        existing.calendar_id = "user@gmail.com"  # already resolved

        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = existing

        with patch("modules.calendar.service.encrypt_token", side_effect=lambda t: f"enc:{t}"):
            CalendarService.upsert_integration(
                db,
                org_id=ORG_ID,
                access_token="new_tok",
                refresh_token="new_ref",
                token_expiry=None,
                calendar_email="user@gmail.com",
                calendar_id="primary",  # fallback, should not overwrite
            )

        # calendar_id must remain the resolved email, not "primary"
        assert existing.calendar_id == "user@gmail.com"


# ---------------------------------------------------------------------------
# Issue 3: FreeBusy key mismatch detection
# ---------------------------------------------------------------------------


class TestFreeBusyKeyMismatch:
    """_check_slot_sync must log a warning when the response key doesn't match
    the stored calendar_id, and still treat the slot as available (not falsely busy)."""

    def test_key_mismatch_treats_slot_as_available_and_logs_warning(self):
        """If the response key is the email but calendar_id is 'primary', the
        code must warn about the mismatch and return True (available) rather
        than raising or returning False."""
        svc = CalendarService()
        row = _make_row(calendar_id="primary")

        # Google returns the real email as the key, NOT "primary"
        fb_response = {
            "calendars": {
                "user@gmail.com": {"busy": [{"start": "2026-07-15T10:00:00Z", "end": "2026-07-15T11:00:00Z"}]}
            }
        }
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.return_value = fb_response

        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
            patch("modules.calendar.service.log") as mock_log,
        ):
            result = svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)

        # Key mismatch: "primary" not in {"user@gmail.com": ...} → busy=[] → True
        assert result is True

        # Warning must have been emitted
        warning_calls = [str(c) for c in mock_log.warning.call_args_list]
        assert any("MISMATCH" in c or "mismatch" in c.lower() for c in warning_calls), (
            f"Expected SLOT_CHECK_KEY_MISMATCH warning, got: {warning_calls}"
        )

    def test_matching_key_reads_real_busy_periods(self):
        """When the response key matches the stored calendar_id, busy periods are read."""
        svc = CalendarService()
        row = _make_row(calendar_id=REAL_CAL_ID)

        fb_response = {
            "calendars": {
                REAL_CAL_ID: {
                    "busy": [
                        {
                            "start": _FUTURE_START.isoformat(),
                            "end": (_FUTURE_START + timedelta(hours=1)).isoformat(),
                        }
                    ]
                }
            }
        }
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.return_value = fb_response

        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
        ):
            result = svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)

        assert result is False  # slot is genuinely busy

    def test_free_slot_with_real_calendar_id(self):
        """An empty calendar with the correct email-based calendar_id returns True."""
        svc = CalendarService()
        row = _make_row(calendar_id=REAL_CAL_ID)

        fb_response = {"calendars": {REAL_CAL_ID: {"busy": []}}}
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.return_value = fb_response

        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
        ):
            result = svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)

        assert result is True

    def test_build_service_failure_raises_calendar_api_error(self):
        """If _build_service raises, it must be wrapped in CalendarAPIError,
        not propagate as a bare Exception (which would trigger the wrong handler)."""
        svc = CalendarService()
        row = _make_row()

        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", side_effect=RuntimeError("discovery failed")),
        ):
            with pytest.raises(CalendarAPIError, match="discovery failed"):
                svc._check_slot_sync(row, start=_FUTURE_START, duration_minutes=30)

    def test_fetch_free_slots_build_service_failure_raises_calendar_api_error(self):
        """Same guarantee for _fetch_free_slots_sync."""
        svc = CalendarService()
        row = _make_row()

        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", side_effect=RuntimeError("no network")),
            patch(
                "modules.calendar.service._utcnow",
                return_value=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            ),
        ):
            with pytest.raises(CalendarAPIError, match="no network"):
                svc._fetch_free_slots_sync(
                    row,
                    target_date=date(2026, 7, 15),
                    duration_minutes=30,
                    tz_name="UTC",
                    count=3,
                )


# ---------------------------------------------------------------------------
# Issue 4: alternatives error handling
# ---------------------------------------------------------------------------


class TestAlternativesErrorHandling:
    """When the alternatives lookup fails with an unexpected exception, the
    handler must NOT fall back to alternatives=[] and say "that time is fully
    booked" — it must surface the real error and go to PHASE_FAILED."""

    @pytest.mark.asyncio
    async def test_unexpected_exception_in_alternatives_fails_gracefully(self):
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=False)  # slot IS busy
        # Simulate an unexpected error during alternatives fetch
        cal.get_free_slots = AsyncMock(side_effect=RuntimeError("unexpected DB error"))

        state = _make_state()
        handler, _, _ = _make_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        # Must NOT say "That time is fully booked" — that was the false positive
        speak = (result.speak_override or "").lower()
        assert "fully booked" not in speak, (
            "Unexpected exception was silently converted to 'that time is fully booked'"
        )
        assert result.consumed
        assert state.phase == PHASE_FAILED

    @pytest.mark.asyncio
    async def test_calendar_api_error_in_alternatives_fails_gracefully(self):
        """CalendarAPIError during alternatives fetch → PHASE_FAILED, not 'fully booked'."""
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=False)
        cal.get_free_slots = AsyncMock(side_effect=CalendarAPIError("rate limit"))

        state = _make_state()
        handler, _, _ = _make_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.consumed
        assert state.phase == PHASE_FAILED
        assert "fully booked" not in (result.speak_override or "").lower()

    @pytest.mark.asyncio
    async def test_busy_slot_with_good_alternatives_shows_options(self):
        """The happy-path busy case still works: alternatives shown, PHASE_SUGGESTING."""
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=False)
        cal.get_free_slots = AsyncMock(return_value=[_ALT_SLOT])

        state = _make_state()
        handler, _, _ = _make_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.consumed
        assert "taken" in (result.speak_override or "").lower()
        assert state.phase == PHASE_SUGGESTING


# ---------------------------------------------------------------------------
# Issue 5: timezone-aware today_iso
# ---------------------------------------------------------------------------


class TestTodayInTimezone:
    """_today_in_timezone must return the correct date for various IANA timezones."""

    _ANCHOR_UTC = datetime(2026, 7, 15, 23, 30, tzinfo=timezone.utc)  # 23:30 UTC

    def test_utc_returns_utc_date(self):
        result = _today_in_timezone("UTC", _now=self._ANCHOR_UTC)
        assert result == "2026-07-15"

    def test_ist_past_midnight_utc_returns_next_day(self):
        """At 23:30 UTC, IST (UTC+5:30) is 05:00 on 2026-07-16."""
        result = _today_in_timezone("Asia/Kolkata", _now=self._ANCHOR_UTC)
        assert result == "2026-07-16"

    def test_us_eastern_before_midnight_utc_returns_previous_day(self):
        """At 02:00 UTC, America/New_York (EDT = UTC-4) is 22:00 on 2026-07-14."""
        anchor = datetime(2026, 7, 15, 2, 0, tzinfo=timezone.utc)
        result = _today_in_timezone("America/New_York", _now=anchor)
        assert result == "2026-07-14"

    def test_same_day_in_utc_and_ist_morning(self):
        """At 08:00 UTC, both UTC and IST (13:30 IST) are still on the same date."""
        anchor = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)
        assert _today_in_timezone("UTC", _now=anchor) == "2026-07-15"
        assert _today_in_timezone("Asia/Kolkata", _now=anchor) == "2026-07-15"

    def test_invalid_timezone_falls_back_to_utc(self):
        """An unrecognised IANA timezone string must fall back to UTC silently."""
        result = _today_in_timezone("Mars/Olympus_Mons", _now=self._ANCHOR_UTC)
        assert result == "2026-07-15"  # UTC fallback


class TestExtractSlotPreferenceTimezone:
    """extract_slot_preference must pass timezone context to the LLM so that
    local times are converted to UTC correctly."""

    @pytest.mark.asyncio
    async def test_prompt_includes_timezone_name(self):
        """Verify the LLM receives the correct timezone in the prompt."""
        from modules.ai.booking_intents import extract_slot_preference
        from modules.ai.schema import ChatMessage

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.text = '{"type": "specific", "parsed_dt": "2026-07-16T09:30:00+00:00", "raw": "3pm tomorrow", "confidence": 0.95}'
        mock_client.complete = AsyncMock(return_value=mock_result)

        result = await extract_slot_preference(
            "3pm tomorrow",
            today_iso="2026-07-15",
            timezone_name="Asia/Kolkata",
            openai_client=mock_client,
        )

        assert result.type == "specific"
        assert result.parsed_dt == "2026-07-16T09:30:00+00:00"

        # The prompt sent to the LLM must mention the user's timezone
        prompt_text = mock_client.complete.call_args[0][0][0].content
        assert "Asia/Kolkata" in prompt_text, "Timezone not passed to LLM prompt"
        # Prompt must NOT say "UTC" as the user's timezone when it's actually IST
        assert "The user is in timezone UTC" not in prompt_text

    @pytest.mark.asyncio
    async def test_leniency_on_partial_json(self):
        """Should return 'unclear' if LLM returns malformed JSON rather than crashing."""
        from modules.ai.booking_intents import extract_slot_preference

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "I cannot determine the time."
        mock_client.complete = AsyncMock(return_value=mock_result)

        result = await extract_slot_preference(
            "some time",
            today_iso="2026-07-15",
            timezone_name="UTC",
            openai_client=mock_client,
        )

        assert result.type == "unclear"


# ---------------------------------------------------------------------------
# End-to-end: process_turn with correct calendar_id
# ---------------------------------------------------------------------------


class TestProcessTurnWithRealCalendarId:
    """Integration-style test: _check_and_book_or_suggest uses the correct
    calendar_id (email) and booking succeeds when that slot is free."""

    @pytest.mark.asyncio
    async def test_free_slot_books_successfully_with_email_calendar_id(self):
        """Full flow with a resolved email calendar_id."""
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=True)
        cal.book_meeting = AsyncMock(return_value=_BOOKED_EVENT)

        state = _make_state(timezone="Asia/Kolkata")
        handler, _, _ = _make_handler(cal_svc=cal, state=state)

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
    async def test_process_turn_asking_time_uses_lead_timezone(self):
        """When in PHASE_ASKING_TIME the handler uses the lead's timezone, not UTC."""
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=True)
        cal.book_meeting = AsyncMock(return_value=_BOOKED_EVENT)

        state = _make_state(phase=PHASE_ASKING_TIME, timezone="America/New_York")
        handler, _, mem = _make_handler(cal_svc=cal, state=state)

        captured_today_iso: list[str] = []
        captured_tz_name: list[str] = []

        async def fake_extract(text, *, today_iso, timezone_name, openai_client):
            captured_today_iso.append(today_iso)
            captured_tz_name.append(timezone_name)
            return SlotPreference(
                type="specific",
                parsed_dt=_FUTURE_START.isoformat(),
                raw="3pm tomorrow",
                confidence=0.9,
            )

        with (
            patch("modules.ai.booking_handler.extract_slot_preference", fake_extract),
            patch("modules.ai.booking_handler.SessionLocal"),
            patch.object(handler, "_send_confirmation", AsyncMock()),
            patch("modules.ai.booking_handler.asyncio.create_task"),
        ):
            await handler.process_turn(
                call_id=CALL_ID,
                user_text="tomorrow at 3pm",
                agent_text="",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
                timezone="America/New_York",
            )

        assert captured_tz_name == ["America/New_York"]
        # today_iso must be computed in America/New_York, not UTC
        # (Just check it was passed through; exact date depends on test time)
        assert len(captured_today_iso) == 1
        assert len(captured_today_iso[0]) == 10

    @pytest.mark.asyncio
    async def test_api_failure_is_not_reported_as_slot_booked(self):
        """A CalendarAPIError must produce an error message, never 'that time is taken'."""
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(side_effect=CalendarAPIError("500 Internal"))

        state = _make_state()
        handler, _, _ = _make_handler(cal_svc=cal, state=state)

        with patch("modules.ai.booking_handler.SessionLocal"):
            result = await handler._check_and_book_or_suggest(state, _FUTURE_START)

        assert result.consumed
        speak = (result.speak_override or "").lower()
        assert "taken" not in speak
        assert "booked" not in speak or "team" in speak
        assert state.phase == PHASE_FAILED


# ---------------------------------------------------------------------------
# Issue 6: free-slot generation with resolved calendar_id (email)
# ---------------------------------------------------------------------------


class TestFreeSlotGenerationWithRealId:
    """_fetch_free_slots_sync must correctly find free slots when the calendar_id
    is an email address (the resolved form of 'primary')."""

    def _run_with_email_id(
        self,
        *,
        busy_periods: list,
        now: datetime,
        tz_name: str = "UTC",
    ) -> list[FreeSlot]:
        svc = CalendarService()
        row = _make_row(calendar_id=REAL_CAL_ID)
        target = date(2026, 7, 15)

        fb_response = {"calendars": {REAL_CAL_ID: {"busy": busy_periods}}}
        mock_google_svc = MagicMock()
        mock_google_svc.freebusy().query().execute.return_value = fb_response

        with (
            patch.object(svc, "_build_credentials", return_value=MagicMock()),
            patch.object(svc, "_build_service", return_value=mock_google_svc),
            patch("modules.calendar.service._utcnow", return_value=now),
        ):
            return svc._fetch_free_slots_sync(
                row,
                target_date=target,
                duration_minutes=30,
                tz_name=tz_name,
                count=3,
            )

    def test_empty_calendar_returns_slots(self):
        now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
        slots = self._run_with_email_id(busy_periods=[], now=now)
        assert len(slots) == 3

    def test_busy_all_day_returns_no_slots(self):
        now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
        busy = [{"start": "2026-07-15T09:00:00+00:00", "end": "2026-07-15T18:00:00+00:00"}]
        slots = self._run_with_email_id(busy_periods=busy, now=now)
        assert slots == []

    def test_ist_timezone_uses_correct_window(self):
        """9am-6pm IST = 03:30-12:30 UTC; slots must be in that UTC range."""
        now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
        slots = self._run_with_email_id(busy_periods=[], now=now, tz_name="Asia/Kolkata")
        assert len(slots) > 0
        ist_window_start_utc = datetime(2026, 7, 15, 3, 30, tzinfo=timezone.utc)
        ist_window_end_utc = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)
        for s in slots:
            assert s.start >= ist_window_start_utc
            assert s.end <= ist_window_end_utc

    def test_us_eastern_timezone_uses_correct_window(self):
        """9am-6pm EST (UTC-5) = 14:00-23:00 UTC."""
        now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
        slots = self._run_with_email_id(
            busy_periods=[], now=now, tz_name="America/New_York"
        )
        assert len(slots) > 0
        est_window_start_utc = datetime(2026, 7, 15, 13, 0, tzinfo=timezone.utc)  # EDT UTC-4
        for s in slots:
            assert s.start >= est_window_start_utc
