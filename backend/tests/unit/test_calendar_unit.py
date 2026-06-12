"""Unit tests for the Google Calendar integration.

Tests are fully offline — no real Google API, Redis, or Postgres calls.
All external dependencies are mocked.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from modules.calendar.encryption import decrypt_token, encrypt_token
from modules.calendar.exceptions import (
    CalendarAuthError,
    CalendarError,
    NoCalendarError,
    SlotUnavailableError,
)
from modules.calendar.schema import BookedEvent, FreeSlot
from modules.ai.booking_state import (
    PHASE_ASKING_TIME,
    PHASE_BOOKED,
    PHASE_CONFIRMING,
    PHASE_FAILED,
    PHASE_IDLE,
    PHASE_SUGGESTING,
    BookingState,
)
from modules.ai.meeting import (
    MEETING_STATUS_BOOKED,
    MEETING_STATUS_NOT_BOOKED,
    MEETING_STATUS_UNKNOWN,
    detect_status,
)


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        token = "ya29.some_access_token_value"
        enc = encrypt_token(token)
        assert enc != token
        assert decrypt_token(enc) == token

    def test_different_encryptions_of_same_value(self):
        token = "same_token"
        assert encrypt_token(token) != encrypt_token(token)  # Fernet adds IV

    def test_decrypt_invalid_ciphertext_raises(self):
        from modules.calendar.exceptions import CalendarError
        with pytest.raises(CalendarError):
            decrypt_token("this-is-not-valid-ciphertext")

    def test_missing_key_raises(self):
        from config.settings import settings
        original = settings.TOKEN_ENCRYPTION_KEY
        settings.TOKEN_ENCRYPTION_KEY = ""
        try:
            with pytest.raises(CalendarError):
                encrypt_token("anything")
        finally:
            settings.TOKEN_ENCRYPTION_KEY = original


# ---------------------------------------------------------------------------
# BookingState serialization
# ---------------------------------------------------------------------------


class TestBookingState:
    def test_default_state(self):
        s = BookingState()
        assert s.phase == PHASE_IDLE
        assert s.lead_email == ""
        assert s.suggested_slots == []

    def test_roundtrip_json(self):
        s = BookingState(
            phase=PHASE_ASKING_TIME,
            lead_email="lead@example.com",
            lead_name="Alice",
            org_id=str(uuid.uuid4()),
            call_id="call-abc",
            parsed_dt="2026-06-12T15:00:00+00:00",
            suggested_slots=[{"start": "2026-06-12T14:00:00+00:00", "end": "2026-06-12T14:30:00+00:00", "start_display": "2 PM", "duration_minutes": 30}],
        )
        restored = BookingState.from_json(s.to_json())
        assert restored.phase == PHASE_ASKING_TIME
        assert restored.lead_email == "lead@example.com"
        assert restored.parsed_dt == "2026-06-12T15:00:00+00:00"
        assert len(restored.suggested_slots) == 1

    def test_from_json_ignores_unknown_fields(self):
        data = {"phase": "idle", "unknown_field": "foo"}
        s = BookingState.from_json(json.dumps(data))
        assert s.phase == PHASE_IDLE


# ---------------------------------------------------------------------------
# Meeting status detection (legacy regex — still used when no calendar)
# ---------------------------------------------------------------------------


class TestMeetingStatusDetection:
    def test_no_booking_in_idle_conversation(self):
        result = detect_status(
            current=MEETING_STATUS_NOT_BOOKED,
            user_text="Tell me more about your pricing.",
            agent_text="Of course! Our pricing starts at $99/month.",
        )
        assert result == MEETING_STATUS_NOT_BOOKED

    def test_confirmation_with_scheduling_context_flips_to_booked(self):
        result = detect_status(
            current=MEETING_STATUS_NOT_BOOKED,
            user_text="yes, that works for me",
            agent_text="How about Thursday at 3 PM for a demo?",
        )
        assert result == MEETING_STATUS_BOOKED

    def test_bare_yes_without_context_stays_not_booked(self):
        result = detect_status(
            current=MEETING_STATUS_NOT_BOOKED,
            user_text="yes",
            agent_text="Great to hear from you!",
        )
        assert result == MEETING_STATUS_NOT_BOOKED

    def test_booked_status_never_downgrades(self):
        result = detect_status(
            current=MEETING_STATUS_BOOKED,
            user_text="actually never mind",
            agent_text="Ok",
        )
        assert result == MEETING_STATUS_BOOKED

    def test_see_you_then_implies_booked(self):
        result = detect_status(
            current=MEETING_STATUS_NOT_BOOKED,
            user_text="see you thursday",
            agent_text="Perfect, your meeting is booked for Thursday at 3 PM.",
        )
        assert result == MEETING_STATUS_BOOKED


# ---------------------------------------------------------------------------
# CalendarService — _build_credentials naive-UTC fix
# ---------------------------------------------------------------------------


class TestBuildCredentials:
    """Validate that _build_credentials keeps creds.expiry as naive UTC so
    that google-auth's internal _helpers.utcnow() comparison never raises
    TypeError: can't compare offset-naive and offset-aware datetimes.
    """

    def _make_row(self, expiry: datetime):
        from modules.calendar.model import CalendarIntegration

        row = MagicMock(spec=CalendarIntegration)
        row.calendar_id = "vikas.excel2011@gmail.com"
        row.organization_id = uuid.uuid4()
        row.access_token_enc = encrypt_token("fake_access_token")
        row.refresh_token_enc = encrypt_token("fake_refresh_token")
        row.token_expiry = expiry
        return row

    def test_naive_db_expiry_stays_naive_on_creds(self):
        """DB stores naive UTC; expiry on Credentials must remain naive."""
        from modules.calendar.service import CalendarService

        row = self._make_row(expiry=datetime(2099, 1, 1, 0, 0))  # naive, far future
        assert row.token_expiry.tzinfo is None

        mock_creds = MagicMock()
        mock_creds.expiry = datetime(2099, 1, 1, 0, 0)

        with patch("google.oauth2.credentials.Credentials", return_value=mock_creds), \
             patch("google.auth.transport.requests.Request"):
            creds = CalendarService._build_credentials(row)

        # expiry must be naive so google-auth's utcnow() comparison works
        assert creds.expiry is not None
        assert creds.expiry.tzinfo is None, (
            "creds.expiry must be naive UTC — google-auth._helpers.utcnow() is naive "
            "and comparing naive >= aware raises TypeError"
        )

    def test_aware_db_expiry_is_stripped_to_naive(self):
        """If somehow a tz-aware datetime is read from DB, it must be stripped."""
        from modules.calendar.service import CalendarService

        # Simulate an aware datetime coming from DB (e.g. after a bad write)
        row = self._make_row(expiry=datetime(2099, 1, 1, 0, 0, tzinfo=timezone.utc))
        assert row.token_expiry.tzinfo is not None

        mock_creds = MagicMock()
        mock_creds.expiry = datetime(2099, 1, 1, 0, 0)

        with patch("google.oauth2.credentials.Credentials", return_value=mock_creds), \
             patch("google.auth.transport.requests.Request"):
            creds = CalendarService._build_credentials(row)

        assert creds.expiry.tzinfo is None, (
            "Aware expiry from DB must be stripped before setting on Credentials"
        )

    def test_valid_token_skips_refresh(self):
        """Token not near expiry → refresh() must NOT be called."""
        from modules.calendar.service import CalendarService

        future = datetime.utcnow() + timedelta(hours=2)  # naive, far future
        row = self._make_row(expiry=future)

        mock_creds = MagicMock()
        mock_creds.expiry = future

        with patch("google.oauth2.credentials.Credentials", return_value=mock_creds), \
             patch("google.auth.transport.requests.Request"):
            CalendarService._build_credentials(row)

        mock_creds.refresh.assert_not_called()

    def test_expired_token_triggers_refresh(self):
        """Token within 5-min window → refresh() must be called once."""
        from modules.calendar.service import CalendarService

        # Expiry 2 minutes in the future — within the 5-min proactive window
        near_expiry = datetime.utcnow() + timedelta(minutes=2)  # naive
        row = self._make_row(expiry=near_expiry)

        mock_creds = MagicMock()
        mock_creds.expiry = near_expiry
        mock_creds.token = "refreshed_token"

        with patch("google.oauth2.credentials.Credentials", return_value=mock_creds), \
             patch("google.auth.transport.requests.Request"):
            CalendarService._build_credentials(row)

        mock_creds.refresh.assert_called_once()

    def test_refresh_failure_raises_calendar_auth_error(self):
        """If google-auth raises during refresh, CalendarAuthError is raised."""
        from modules.calendar.service import CalendarService
        from modules.calendar.exceptions import CalendarAuthError

        past = datetime.utcnow() - timedelta(hours=1)  # expired
        row = self._make_row(expiry=past)

        mock_creds = MagicMock()
        mock_creds.expiry = past
        mock_creds.refresh.side_effect = Exception("oauth2 error")

        with patch("google.oauth2.credentials.Credentials", return_value=mock_creds), \
             patch("google.auth.transport.requests.Request"):
            with pytest.raises(CalendarAuthError):
                CalendarService._build_credentials(row)

    def test_no_expiry_triggers_refresh(self):
        """creds.expiry=None → needs_refresh=True, refresh() is called."""
        from modules.calendar.service import CalendarService

        row = self._make_row(expiry=None)
        row.token_expiry = None

        mock_creds = MagicMock()
        mock_creds.expiry = None
        mock_creds.token = "fresh_token"

        with patch("google.oauth2.credentials.Credentials", return_value=mock_creds), \
             patch("google.auth.transport.requests.Request"):
            CalendarService._build_credentials(row)

        mock_creds.refresh.assert_called_once()

    def test_google_auth_expired_property_does_not_raise_with_naive_expiry(self):
        """Integration: the real google-auth Credentials.expired property must
        not raise TypeError when expiry is naive (as we now set it)."""
        from google.oauth2.credentials import Credentials as GoogleCredentials

        creds = GoogleCredentials(token="tok")
        # Set naive expiry — as _build_credentials now does
        creds.expiry = datetime(2099, 1, 1, 0, 0)
        assert creds.expiry.tzinfo is None

        # This must NOT raise TypeError
        try:
            _ = creds.expired
            _ = creds.valid
        except TypeError as exc:
            pytest.fail(
                f"creds.expired raised TypeError with naive expiry: {exc}\n"
                "This is the exact bug fixed in _build_credentials."
            )

    def test_google_auth_expired_property_raises_with_aware_expiry(self):
        """Confirm that an aware expiry triggers the original TypeError —
        proving why the fix (naive expiry) is necessary."""
        from google.oauth2.credentials import Credentials as GoogleCredentials

        creds = GoogleCredentials(token="tok")
        # Set AWARE expiry — what the old code did
        creds.expiry = datetime(2099, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert creds.expiry.tzinfo is not None

        # This SHOULD raise TypeError (proves the bug existed)
        with pytest.raises(TypeError, match="offset-naive and offset-aware"):
            _ = creds.expired


# ---------------------------------------------------------------------------
# CalendarService — free slot computation (offline, no real Google API)
# ---------------------------------------------------------------------------


class TestFreeSlotComputation:
    """Test _fetch_free_slots_sync directly with a mocked Google API service."""

    def _make_row(self):
        from modules.calendar.model import CalendarIntegration

        row = MagicMock(spec=CalendarIntegration)
        row.calendar_id = "primary"
        row.access_token_enc = encrypt_token("fake_access_token")
        row.refresh_token_enc = encrypt_token("fake_refresh_token")
        row.token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        return row

    def _make_google_svc_mock(self, busy_periods):
        mock_fb_result = {"calendars": {"primary": {"busy": busy_periods}}}
        mock_google_svc = MagicMock()
        # Ensure chained calls return consistent mocks
        mock_google_svc.freebusy.return_value.query.return_value.execute.return_value = mock_fb_result
        return mock_google_svc

    def test_no_busy_returns_slots(self):
        from modules.calendar.service import CalendarService

        svc = CalendarService()
        row = self._make_row()
        google_svc_mock = self._make_google_svc_mock([])

        with patch.object(svc, "_build_credentials", return_value=MagicMock()), \
             patch.object(svc, "_build_service", return_value=google_svc_mock):
            slots = svc._fetch_free_slots_sync(
                row,
                target_date=date(2026, 6, 20),
                duration_minutes=30,
                tz_name="UTC",
                count=3,
            )

        assert len(slots) > 0
        assert all(isinstance(s, FreeSlot) for s in slots)
        assert all(s.duration_minutes == 30 for s in slots)

    def test_busy_block_excluded_from_slots(self):
        from modules.calendar.service import CalendarService

        busy = [
            {"start": "2026-06-20T09:00:00+00:00", "end": "2026-06-20T11:00:00+00:00"}
        ]
        svc = CalendarService()
        row = self._make_row()
        google_svc_mock = self._make_google_svc_mock(busy)

        with patch.object(svc, "_build_credentials", return_value=MagicMock()), \
             patch.object(svc, "_build_service", return_value=google_svc_mock):
            slots = svc._fetch_free_slots_sync(
                row,
                target_date=date(2026, 6, 20),
                duration_minutes=30,
                tz_name="UTC",
                count=5,
            )

        busy_start = datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)
        busy_end = datetime(2026, 6, 20, 11, 0, tzinfo=timezone.utc)
        for slot in slots:
            assert not (slot.start < busy_end and slot.end > busy_start), \
                f"Slot {slot.start}–{slot.end} overlaps busy block"

    def test_count_limit_respected(self):
        from modules.calendar.service import CalendarService

        svc = CalendarService()
        row = self._make_row()
        google_svc_mock = self._make_google_svc_mock([])

        with patch.object(svc, "_build_credentials", return_value=MagicMock()), \
             patch.object(svc, "_build_service", return_value=google_svc_mock):
            slots = svc._fetch_free_slots_sync(
                row,
                target_date=date(2026, 6, 20),
                duration_minutes=30,
                tz_name="UTC",
                count=2,
            )

        assert len(slots) <= 2

    def test_fully_busy_day_returns_empty(self):
        from modules.calendar.service import CalendarService

        busy = [
            {"start": "2026-06-20T00:00:00+00:00", "end": "2026-06-20T23:59:00+00:00"}
        ]
        svc = CalendarService()
        row = self._make_row()
        google_svc_mock = self._make_google_svc_mock(busy)

        with patch.object(svc, "_build_credentials", return_value=MagicMock()), \
             patch.object(svc, "_build_service", return_value=google_svc_mock):
            slots = svc._fetch_free_slots_sync(
                row,
                target_date=date(2026, 6, 20),
                duration_minutes=30,
                tz_name="UTC",
                count=3,
            )

        assert slots == []


# ---------------------------------------------------------------------------
# BookingHandler — state machine transitions (mocked calendar + openai)
# ---------------------------------------------------------------------------


@pytest.fixture
def booking_components():
    """Return mocked CalendarService, BookingMemory, and OpenAI client."""
    from modules.ai.booking_handler import BookingHandler
    from modules.ai.booking_state import BookingMemory

    cal_svc = MagicMock()
    mem = MagicMock(spec=BookingMemory)
    openai_client = MagicMock()

    handler = BookingHandler(
        calendar_svc=cal_svc,
        booking_memory=mem,
        openai_client=openai_client,
    )
    return handler, cal_svc, mem, openai_client


@pytest.mark.asyncio
class TestBookingHandlerStateMachine:
    async def test_no_org_id_returns_empty_result(self, booking_components):
        handler, *_ = booking_components
        result = await handler.process_turn(
            call_id="call-1",
            user_text="yes book a meeting",
            agent_text="",
            org_id=None,
            lead_id=None,
            lead_email="lead@test.com",
            lead_name="Alice",
        )
        assert result.speak_override is None
        assert result.meeting_booked is False

    async def test_no_calendar_connected_returns_empty(self, booking_components):
        handler, cal_svc, mem, _ = booking_components
        from modules.calendar.exceptions import NoCalendarError

        # Simulate no calendar connected
        cal_svc.get_integration.side_effect = NoCalendarError()
        mem.get = AsyncMock(return_value=BookingState())
        mem.save = AsyncMock()

        result = await handler.process_turn(
            call_id="call-1",
            user_text="yes book",
            agent_text="",
            org_id=uuid.uuid4(),
            lead_id=None,
            lead_email="x@x.com",
            lead_name="Bob",
        )
        assert result.speak_override is None

    async def test_booking_intent_detected_transitions_to_asking_time(
        self, booking_components
    ):
        handler, cal_svc, mem, openai_client = booking_components

        # Simulate calendar connected
        cal_svc.get_integration.return_value = MagicMock()

        state = BookingState(phase=PHASE_IDLE, call_id="call-2")
        mem.get = AsyncMock(return_value=state)
        mem.save = AsyncMock()

        # GPT says "book" intent
        with patch(
            "modules.ai.booking_handler.detect_booking_intent",
            new=AsyncMock(return_value="book"),
        ):
            result = await handler.process_turn(
                call_id="call-2",
                user_text="yes let's schedule a meeting",
                agent_text="",
                org_id=uuid.uuid4(),
                lead_id=None,
                lead_email="lead@test.com",
                lead_name="Alice",
            )

        assert result.speak_override == "Great! What date and time works best for you?"
        assert result.consumed is True
        assert state.phase == PHASE_ASKING_TIME

    async def test_no_intent_stays_idle(self, booking_components):
        handler, cal_svc, mem, _ = booking_components

        cal_svc.get_integration.return_value = MagicMock()
        state = BookingState(phase=PHASE_IDLE, call_id="call-3")
        mem.get = AsyncMock(return_value=state)
        mem.save = AsyncMock()

        with patch(
            "modules.ai.booking_handler.detect_booking_intent",
            new=AsyncMock(return_value="none"),
        ):
            result = await handler.process_turn(
                call_id="call-3",
                user_text="Can you tell me more about your product?",
                agent_text="",
                org_id=uuid.uuid4(),
                lead_id=None,
                lead_email="lead@test.com",
                lead_name="Alice",
            )

        assert result.speak_override is None
        assert result.consumed is False
        assert state.phase == PHASE_IDLE

    async def test_specific_slot_available_books_immediately(self, booking_components):
        handler, cal_svc, mem, _ = booking_components

        cal_svc.get_integration.return_value = MagicMock()
        org_id = uuid.uuid4()
        state = BookingState(
            phase=PHASE_ASKING_TIME,
            lead_email="lead@test.com",
            lead_name="Alice",
            org_id=str(org_id),
            call_id="call-4",
            timezone="UTC",
            duration_minutes=30,
        )
        mem.get = AsyncMock(return_value=state)
        mem.save = AsyncMock()

        from modules.ai.booking_intents import SlotPreference

        # Slot is available
        cal_svc.is_slot_available = AsyncMock(return_value=True)

        booked_event = BookedEvent(
            event_id="evt_123",
            meet_link="https://meet.google.com/abc-def-ghi",
            html_link="https://calendar.google.com/event?eid=xyz",
            start_iso="2026-06-20T15:00:00+00:00",
            end_iso="2026-06-20T15:30:00+00:00",
            start_display="June 20 at 3:00 PM",
            title="Meeting",
        )
        cal_svc.book_meeting = AsyncMock(return_value=booked_event)

        with patch(
            "modules.ai.booking_handler.extract_slot_preference",
            new=AsyncMock(
                return_value=SlotPreference(
                    type="specific",
                    parsed_dt="2026-06-20T15:00:00+00:00",
                    raw="tomorrow at 3 PM",
                    confidence=0.95,
                )
            ),
        ), patch(
            "modules.ai.booking_handler.BookingHandler._send_confirmation",
            new=AsyncMock(),
        ), patch(
            "modules.ai.booking_handler.BookingHandler._log_activity",
            new=AsyncMock(),
        ):
            result = await handler.process_turn(
                call_id="call-4",
                user_text="tomorrow at 3 PM",
                agent_text="",
                org_id=org_id,
                lead_id=None,
                lead_email="lead@test.com",
                lead_name="Alice",
            )

        assert result.meeting_booked is True
        assert result.meet_link == "https://meet.google.com/abc-def-ghi"
        assert "booked" in result.speak_override.lower() or "scheduled" in result.speak_override.lower() or "confirmed" in result.speak_override.lower() or "meeting" in result.speak_override.lower()
        assert state.phase == PHASE_BOOKED

    async def test_slot_unavailable_offers_alternatives(self, booking_components):
        handler, cal_svc, mem, _ = booking_components

        cal_svc.get_integration.return_value = MagicMock()
        org_id = uuid.uuid4()
        state = BookingState(
            phase=PHASE_ASKING_TIME,
            lead_email="lead@test.com",
            lead_name="Alice",
            org_id=str(org_id),
            call_id="call-5",
            timezone="UTC",
            duration_minutes=30,
        )
        mem.get = AsyncMock(return_value=state)
        mem.save = AsyncMock()

        from modules.ai.booking_intents import SlotPreference

        # Slot is NOT available
        cal_svc.is_slot_available = AsyncMock(return_value=False)
        # Return 3 alternatives
        cal_svc.get_free_slots = AsyncMock(
            return_value=[
                FreeSlot(
                    start=datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc),
                    end=datetime(2026, 6, 20, 14, 30, tzinfo=timezone.utc),
                    start_display="2:00 PM",
                    duration_minutes=30,
                ),
                FreeSlot(
                    start=datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc),
                    end=datetime(2026, 6, 20, 16, 30, tzinfo=timezone.utc),
                    start_display="4:00 PM",
                    duration_minutes=30,
                ),
            ]
        )

        with patch(
            "modules.ai.booking_handler.extract_slot_preference",
            new=AsyncMock(
                return_value=SlotPreference(
                    type="specific",
                    parsed_dt="2026-06-20T15:00:00+00:00",
                    raw="3 PM",
                    confidence=0.9,
                )
            ),
        ):
            result = await handler.process_turn(
                call_id="call-5",
                user_text="3 PM tomorrow",
                agent_text="",
                org_id=org_id,
                lead_id=None,
                lead_email="lead@test.com",
                lead_name="Alice",
            )

        assert result.meeting_booked is False
        assert result.speak_override is not None
        # Should mention alternatives
        assert "2:00 PM" in result.speak_override or "4:00 PM" in result.speak_override or "taken" in result.speak_override
        assert state.phase == PHASE_SUGGESTING

    async def test_flexible_preference_leads_to_confirming(self, booking_components):
        handler, cal_svc, mem, _ = booking_components

        cal_svc.get_integration.return_value = MagicMock()
        org_id = uuid.uuid4()
        state = BookingState(
            phase=PHASE_ASKING_TIME,
            lead_email="lead@test.com",
            lead_name="Alice",
            org_id=str(org_id),
            call_id="call-6",
            timezone="UTC",
            duration_minutes=30,
        )
        mem.get = AsyncMock(return_value=state)
        mem.save = AsyncMock()

        from modules.ai.booking_intents import SlotPreference

        cal_svc.get_free_slots = AsyncMock(
            return_value=[
                FreeSlot(
                    start=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
                    end=datetime(2026, 6, 20, 10, 30, tzinfo=timezone.utc),
                    start_display="10:00 AM",
                    duration_minutes=30,
                )
            ]
        )

        with patch(
            "modules.ai.booking_handler.extract_slot_preference",
            new=AsyncMock(
                return_value=SlotPreference(
                    type="flexible",
                    parsed_dt=None,
                    raw="any time works",
                    confidence=0.99,
                )
            ),
        ):
            result = await handler.process_turn(
                call_id="call-6",
                user_text="any time works for me",
                agent_text="",
                org_id=org_id,
                lead_id=None,
                lead_email="lead@test.com",
                lead_name="Alice",
            )

        assert result.speak_override is not None
        assert "10:00 AM" in result.speak_override
        assert state.phase == PHASE_CONFIRMING

    async def test_booked_phase_is_noop(self, booking_components):
        handler, cal_svc, mem, _ = booking_components

        cal_svc.get_integration.return_value = MagicMock()
        state = BookingState(
            phase=PHASE_BOOKED,
            call_id="call-7",
            org_id=str(uuid.uuid4()),
        )
        mem.get = AsyncMock(return_value=state)
        mem.save = AsyncMock()

        result = await handler.process_turn(
            call_id="call-7",
            user_text="great, thanks!",
            agent_text="",
            org_id=uuid.uuid4(),
            lead_id=None,
            lead_email="x@x.com",
            lead_name="X",
        )
        assert result.meeting_booked is True
        assert result.speak_override is None

    async def test_confirmation_word_triggers_booking(self, booking_components):
        handler, cal_svc, mem, _ = booking_components

        cal_svc.get_integration.return_value = MagicMock()
        org_id = uuid.uuid4()
        state = BookingState(
            phase=PHASE_CONFIRMING,
            lead_email="lead@test.com",
            lead_name="Alice",
            org_id=str(org_id),
            call_id="call-8",
            parsed_dt="2026-06-20T10:00:00+00:00",
            timezone="UTC",
            duration_minutes=30,
        )
        mem.get = AsyncMock(return_value=state)
        mem.save = AsyncMock()

        booked_event = BookedEvent(
            event_id="evt_456",
            meet_link="https://meet.google.com/xxx-yyy-zzz",
            html_link="https://calendar.google.com/event?eid=abc",
            start_iso="2026-06-20T10:00:00+00:00",
            end_iso="2026-06-20T10:30:00+00:00",
            start_display="June 20 at 10:00 AM",
            title="Meeting",
        )
        cal_svc.is_slot_available = AsyncMock(return_value=True)
        cal_svc.book_meeting = AsyncMock(return_value=booked_event)

        with patch(
            "modules.ai.booking_handler.BookingHandler._send_confirmation",
            new=AsyncMock(),
        ), patch(
            "modules.ai.booking_handler.BookingHandler._log_activity",
            new=AsyncMock(),
        ):
            result = await handler.process_turn(
                call_id="call-8",
                user_text="yes, perfect!",
                agent_text="",
                org_id=org_id,
                lead_id=None,
                lead_email="lead@test.com",
                lead_name="Alice",
            )

        assert result.meeting_booked is True
        assert state.phase == PHASE_BOOKED

    async def test_calendar_api_error_triggers_failed_phase(self, booking_components):
        handler, cal_svc, mem, _ = booking_components

        cal_svc.get_integration.return_value = MagicMock()
        org_id = uuid.uuid4()
        state = BookingState(
            phase=PHASE_ASKING_TIME,
            lead_email="lead@test.com",
            lead_name="Alice",
            org_id=str(org_id),
            call_id="call-9",
            parsed_dt="2026-06-20T15:00:00+00:00",
            timezone="UTC",
            duration_minutes=30,
        )
        mem.get = AsyncMock(return_value=state)
        mem.save = AsyncMock()

        from modules.ai.booking_intents import SlotPreference
        from modules.calendar.exceptions import CalendarAPIError

        cal_svc.is_slot_available = AsyncMock(return_value=True)
        cal_svc.book_meeting = AsyncMock(side_effect=CalendarAPIError("Google API down"))

        with patch(
            "modules.ai.booking_handler.extract_slot_preference",
            new=AsyncMock(
                return_value=SlotPreference(
                    type="specific",
                    parsed_dt="2026-06-20T15:00:00+00:00",
                    raw="3 PM",
                    confidence=0.9,
                )
            ),
        ):
            result = await handler.process_turn(
                call_id="call-9",
                user_text="3 PM tomorrow",
                agent_text="",
                org_id=org_id,
                lead_id=None,
                lead_email="lead@test.com",
                lead_name="Alice",
            )

        assert result.meeting_booked is False
        assert state.phase == PHASE_FAILED
        assert result.speak_override is not None
        # Should be a graceful fallback message
        assert len(result.speak_override) > 10
