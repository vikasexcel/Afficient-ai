"""Unit tests for the BookingHandler state machine.

All external I/O (Redis, Postgres, Google Calendar, SMTP) is mocked.
Tests run fully offline.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ai.booking_handler import (
    BookingHandler,
    BookingTurnResult,
    _agent_offered_meeting,
    _extract_email,
    _is_confirmation,
    _is_valid_email,
)
from modules.ai.booking_state import (
    PHASE_ASKING_EMAIL,
    PHASE_ASKING_TIME,
    PHASE_BOOKED,
    PHASE_CONFIRMING,
    PHASE_FAILED,
    PHASE_IDLE,
    BookingMemory,
    BookingState,
)
from modules.calendar.exceptions import CalendarAuthError, CalendarError, NoCalendarError
from modules.calendar.schema import BookedEvent, FreeSlot


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
CALL_ID = "test-call-123"


def _make_state(**kwargs) -> BookingState:
    defaults = dict(
        phase=PHASE_IDLE,
        lead_email="lead@example.com",
        lead_name="Test Lead",
        org_id=str(ORG_ID),
        call_id=CALL_ID,
        timezone="UTC",
        duration_minutes=30,
    )
    defaults.update(kwargs)
    return BookingState(**defaults)


def _make_booked_event(**kwargs) -> BookedEvent:
    defaults = dict(
        event_id="evt_abc123",
        meet_link="https://meet.google.com/abc-xyz",
        html_link="https://calendar.google.com/event?eid=abc",
        start_iso="2026-06-20T10:00:00+00:00",
        end_iso="2026-06-20T10:30:00+00:00",
        start_display="Saturday, June 20 at 10:00 AM UTC",
        title="Meeting",
    )
    defaults.update(kwargs)
    return BookedEvent(**defaults)


def _make_free_slot(start_display: str = "Saturday, June 20 at 10:00 AM UTC") -> FreeSlot:
    return FreeSlot(
        start=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 20, 10, 30, tzinfo=timezone.utc),
        start_display=start_display,
        duration_minutes=30,
    )


def _make_handler(
    *,
    calendar_svc: Optional[MagicMock] = None,
    memory_state: Optional[BookingState] = None,
) -> tuple[BookingHandler, MagicMock, AsyncMock]:
    """Return (handler, mock_calendar_svc, mock_memory)."""
    cal = calendar_svc or MagicMock()
    mem = AsyncMock(spec=BookingMemory)

    state = memory_state or _make_state()
    mem.get = AsyncMock(return_value=state)
    mem.save = AsyncMock()

    openai = MagicMock()
    handler = BookingHandler(calendar_svc=cal, booking_memory=mem, openai_client=openai)
    return handler, cal, mem


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_extract_email_plain(self):
        assert _extract_email("my email is john@example.com") == "john@example.com"

    def test_extract_email_uppercase_normalised(self):
        assert _extract_email("Send to John@Example.COM please") == "john@example.com"

    def test_extract_email_none_when_absent(self):
        assert _extract_email("no address here") is None

    def test_is_valid_email_accepts_normal(self):
        assert _is_valid_email("user@domain.co") is True

    def test_is_valid_email_rejects_partial(self):
        assert _is_valid_email("notanemail") is False

    def test_is_valid_email_rejects_empty(self):
        assert _is_valid_email("") is False

    def test_is_confirmation_yes(self):
        assert _is_confirmation("yes") is True

    def test_is_confirmation_sure(self):
        assert _is_confirmation("sure, go ahead") is True

    def test_is_confirmation_negative(self):
        assert _is_confirmation("no thanks") is False

    def test_agent_offered_meeting_schedule(self):
        assert _agent_offered_meeting("Would you like to schedule a meeting?") is True

    def test_agent_offered_meeting_book_call(self):
        assert _agent_offered_meeting("I can book a call for you.") is True

    def test_agent_offered_meeting_false(self):
        assert _agent_offered_meeting("Let me tell you about our pricing.") is False


# ---------------------------------------------------------------------------
# process_turn — missing org_id
# ---------------------------------------------------------------------------


class TestProcessTurnGuards:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_org_id(self):
        handler, _, _ = _make_handler()
        result = await handler.process_turn(
            call_id=CALL_ID,
            user_text="I'd like to book a meeting",
            agent_text="",
            org_id=None,
            lead_id=None,
            lead_email="",
            lead_name="",
        )
        assert result.speak_override is None
        assert not result.consumed


# ---------------------------------------------------------------------------
# Scenario: Successful booking (email pre-seeded)
# ---------------------------------------------------------------------------


class TestSuccessfulBooking:
    @pytest.mark.asyncio
    async def test_full_flow_specific_slot(self):
        """idle → ask time → specific slot available → BOOKED, invite sent."""
        cal = MagicMock()
        cal.get_integration = MagicMock(return_value=MagicMock())  # connected
        cal.is_slot_available = AsyncMock(return_value=True)
        cal.book_meeting = AsyncMock(return_value=_make_booked_event())

        # Phase 1: idle — detect intent
        state_idle = _make_state(phase=PHASE_IDLE)
        handler, _, mem = _make_handler(calendar_svc=cal, memory_state=state_idle)

        with (
            patch("modules.ai.booking_handler.detect_booking_intent", AsyncMock(return_value="book")),
            patch("modules.ai.booking_handler.SessionLocal", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="I want to schedule a meeting",
                agent_text="",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
            )

        assert result.consumed
        assert "date and time" in (result.speak_override or "").lower()
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_ASKING_TIME

    @pytest.mark.asyncio
    async def test_booking_produces_speak_confirmation(self):
        """When _do_book succeeds the result contains the meeting time."""
        cal = MagicMock()
        cal.book_meeting = AsyncMock(return_value=_make_booked_event())

        state = _make_state(
            phase=PHASE_ASKING_TIME,
            lead_email="lead@example.com",
            parsed_dt="2026-06-20T10:00:00+00:00",
        )
        handler, _, mem = _make_handler(calendar_svc=cal, memory_state=state)

        with (
            patch("modules.ai.booking_handler.extract_slot_preference", AsyncMock(
                return_value=MagicMock(type="specific", parsed_dt="2026-06-20T10:00:00+00:00", raw="Saturday at 10am")
            )),
            patch.object(cal, "is_slot_available", AsyncMock(return_value=True)),
            patch("modules.ai.booking_handler.SessionLocal"),
            patch("modules.ai.booking_handler.BookingHandler._send_confirmation", AsyncMock()),
            patch("modules.ai.booking_handler.asyncio.create_task"),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="Saturday at 10 AM",
                agent_text="",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
            )

        assert result.meeting_booked
        assert result.consumed
        assert "booked" in (result.speak_override or "").lower() or "meeting" in (result.speak_override or "").lower()

    @pytest.mark.asyncio
    async def test_past_parsed_slot_is_rejected_before_availability_check(self):
        """If the LLM returns a past datetime, do not report it as bookable."""
        cal = MagicMock()
        cal.is_slot_available = AsyncMock(return_value=True)
        cal.book_meeting = AsyncMock(return_value=_make_booked_event())

        state = _make_state(phase=PHASE_ASKING_TIME)
        handler, _, mem = _make_handler(calendar_svc=cal, memory_state=state)

        with patch(
            "modules.ai.booking_handler.extract_slot_preference",
            AsyncMock(
                return_value=MagicMock(
                    type="specific",
                    parsed_dt="2000-01-01T10:00:00+00:00",
                    raw="tomorrow at 3pm",
                )
            ),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="tomorrow at 3 PM",
                agent_text="",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
            )

        assert result.consumed
        assert "already passed" in (result.speak_override or "").lower()
        assert not result.meeting_booked
        cal.is_slot_available.assert_not_called()
        cal.book_meeting.assert_not_called()
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_ASKING_TIME

    @pytest.mark.asyncio
    async def test_invite_sent_to_lead_on_success(self):
        """_send_confirmation must be awaited with lead email after booking."""
        cal = MagicMock()
        cal.book_meeting = AsyncMock(return_value=_make_booked_event())

        state = _make_state(
            phase=PHASE_CONFIRMING,
            lead_email="lead@example.com",
            parsed_dt="2026-06-20T10:00:00+00:00",
        )
        handler, _, _ = _make_handler(calendar_svc=cal, memory_state=state)

        send_mock = AsyncMock()
        with (
            patch.object(handler, "_send_confirmation", send_mock),
            patch("modules.ai.booking_handler.SessionLocal"),
            patch("modules.ai.booking_handler.asyncio.create_task"),
        ):
            await handler._do_book(state, datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc))

        send_mock.assert_awaited_once()
        call_state = send_mock.call_args[0][0]
        assert call_state.lead_email == "lead@example.com"


# ---------------------------------------------------------------------------
# Scenario: Missing email — agent collects it during the call
# ---------------------------------------------------------------------------


class TestMissingEmailFlow:
    @pytest.mark.asyncio
    async def test_no_email_after_intent_triggers_asking_email(self):
        """When lead_email is empty after intent, phase becomes asking_email."""
        cal = MagicMock()
        cal.get_integration = MagicMock(return_value=MagicMock())

        state = _make_state(phase=PHASE_IDLE, lead_email="")
        handler, _, mem = _make_handler(calendar_svc=cal, memory_state=state)

        with (
            patch("modules.ai.booking_handler.detect_booking_intent", AsyncMock(return_value="book")),
            patch("modules.ai.booking_handler.SessionLocal"),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="yes, book a meeting",
                agent_text="",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="",
                lead_name="Test Lead",
            )

        assert result.consumed
        assert "email" in (result.speak_override or "").lower()
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_ASKING_EMAIL

    @pytest.mark.asyncio
    async def test_valid_email_advances_to_asking_time(self):
        state = _make_state(phase=PHASE_ASKING_EMAIL, lead_email="")
        handler, _, mem = _make_handler(memory_state=state)

        result = await handler.process_turn(
            call_id=CALL_ID,
            user_text="it's john.doe@company.com",
            agent_text="",
            org_id=ORG_ID,
            lead_id=None,
            lead_email="",
            lead_name="Test Lead",
        )

        assert result.consumed
        assert "time" in (result.speak_override or "").lower()
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_ASKING_TIME
        assert saved.lead_email == "john.doe@company.com"

    @pytest.mark.asyncio
    async def test_do_book_redirects_to_asking_email_when_email_empty(self):
        """If _do_book is called with no email it pivots to email collection."""
        state = _make_state(phase=PHASE_ASKING_TIME, lead_email="")
        handler, cal, _ = _make_handler(memory_state=state)

        result = await handler._do_book(state, datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc))

        assert result.consumed
        assert "email" in (result.speak_override or "").lower()
        assert state.phase == PHASE_ASKING_EMAIL
        assert state.parsed_dt is not None  # slot is preserved for after email
        cal.book_meeting.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: Invalid email — retries then graceful fail
# ---------------------------------------------------------------------------


class TestInvalidEmail:
    @pytest.mark.asyncio
    async def test_first_invalid_email_re_asks(self):
        state = _make_state(phase=PHASE_ASKING_EMAIL, lead_email="", email_attempts=0)
        handler, _, mem = _make_handler(memory_state=state)

        result = await handler.process_turn(
            call_id=CALL_ID,
            user_text="my email is just john",
            agent_text="",
            org_id=ORG_ID,
            lead_id=None,
            lead_email="",
            lead_name="Test Lead",
        )

        assert result.consumed
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_ASKING_EMAIL  # still collecting
        assert saved.email_attempts == 1

    @pytest.mark.asyncio
    async def test_exhausted_attempts_transitions_to_failed(self):
        state = _make_state(
            phase=PHASE_ASKING_EMAIL, lead_email="", email_attempts=2
        )
        handler, _, mem = _make_handler(memory_state=state)

        result = await handler.process_turn(
            call_id=CALL_ID,
            user_text="I don't know",
            agent_text="",
            org_id=ORG_ID,
            lead_id=None,
            lead_email="",
            lead_name="Test Lead",
        )

        assert result.consumed
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_FAILED
        assert "team will follow up" in (result.speak_override or "").lower()


# ---------------------------------------------------------------------------
# Scenario: Google Calendar not connected
# ---------------------------------------------------------------------------


class TestCalendarNotConnected:
    @pytest.mark.asyncio
    async def test_no_calendar_surfaces_spoken_error(self):
        """When NoCalendarError is raised after intent, agent speaks an error."""
        cal = MagicMock()
        cal.get_integration = MagicMock(side_effect=NoCalendarError(str(ORG_ID)))

        state = _make_state(phase=PHASE_IDLE)
        handler, _, mem = _make_handler(calendar_svc=cal, memory_state=state)

        with (
            patch("modules.ai.booking_handler.detect_booking_intent", AsyncMock(return_value="book")),
            patch("modules.ai.booking_handler.SessionLocal"),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="I'd like to book a meeting",
                agent_text="",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
            )

        assert result.consumed
        assert result.speak_override is not None
        # Must mention the team will follow up, not silently no-op
        speak = result.speak_override.lower()
        assert "calendar" in speak or "team" in speak or "schedule" in speak
        # Phase must remain idle (not advance to asking_time)
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_IDLE

    @pytest.mark.asyncio
    async def test_calendar_auth_error_surfaces_spoken_error(self):
        cal = MagicMock()
        cal.get_integration = MagicMock(side_effect=CalendarAuthError())

        state = _make_state(phase=PHASE_IDLE)
        handler, _, _ = _make_handler(calendar_svc=cal, memory_state=state)

        with (
            patch("modules.ai.booking_handler.detect_booking_intent", AsyncMock(return_value="book")),
            patch("modules.ai.booking_handler.SessionLocal"),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="let's book a meeting",
                agent_text="",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
            )

        assert result.consumed
        assert result.speak_override is not None

    @pytest.mark.asyncio
    async def test_no_calendar_mid_flow_transitions_to_failed(self):
        """NoCalendarError during slot pick transitions to FAILED with spoken error."""
        cal = MagicMock()
        cal.get_free_slots = AsyncMock(side_effect=NoCalendarError())

        state = _make_state(phase=PHASE_ASKING_TIME)
        handler, _, mem = _make_handler(calendar_svc=cal, memory_state=state)

        with (
            patch("modules.ai.booking_handler.extract_slot_preference", AsyncMock(
                return_value=MagicMock(type="flexible", parsed_dt=None, raw="any time")
            )),
            patch("modules.ai.booking_handler.SessionLocal"),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="any time works",
                agent_text="",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
            )

        assert result.consumed
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_FAILED


# ---------------------------------------------------------------------------
# Scenario: Context-aware intent (agent offered meeting, user says "sure")
# ---------------------------------------------------------------------------


class TestContextAwareIntent:
    @pytest.mark.asyncio
    async def test_yes_after_agent_offer_triggers_booking(self):
        """User says 'sure' after agent offers to schedule — should detect intent."""
        cal = MagicMock()
        cal.get_integration = MagicMock(return_value=MagicMock())

        state = _make_state(phase=PHASE_IDLE, lead_email="lead@example.com")
        handler, _, mem = _make_handler(calendar_svc=cal, memory_state=state)

        detect_mock = AsyncMock(return_value="none")  # LLM would say "none" for "sure" alone
        with (
            patch("modules.ai.booking_handler.detect_booking_intent", detect_mock),
            patch("modules.ai.booking_handler.SessionLocal"),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="sure",
                agent_text="Would you like to schedule a meeting with our team?",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
            )

        # LLM should NOT have been called (short-circuited by context detection)
        detect_mock.assert_not_called()
        assert result.consumed
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_ASKING_TIME

    @pytest.mark.asyncio
    async def test_yes_without_agent_offer_still_uses_llm(self):
        """'yes' with no meeting offer from agent must still call detect_booking_intent."""
        cal = MagicMock()
        cal.get_integration = MagicMock(return_value=MagicMock())

        state = _make_state(phase=PHASE_IDLE)
        handler, _, _ = _make_handler(calendar_svc=cal, memory_state=state)

        detect_mock = AsyncMock(return_value="none")
        with (
            patch("modules.ai.booking_handler.detect_booking_intent", detect_mock),
            patch("modules.ai.booking_handler.SessionLocal"),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="yes",
                agent_text="Our pricing starts at $99 per month.",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="lead@example.com",
                lead_name="Test Lead",
            )

        detect_mock.assert_called_once()
        assert not result.consumed  # LLM returned "none" → no booking triggered

    @pytest.mark.asyncio
    async def test_okay_after_offer_with_missing_email_goes_to_asking_email(self):
        """Context-aware intent + no email → asks for email."""
        cal = MagicMock()
        cal.get_integration = MagicMock(return_value=MagicMock())

        state = _make_state(phase=PHASE_IDLE, lead_email="")
        handler, _, mem = _make_handler(calendar_svc=cal, memory_state=state)

        with (
            patch("modules.ai.booking_handler.detect_booking_intent", AsyncMock(return_value="none")),
            patch("modules.ai.booking_handler.SessionLocal"),
        ):
            result = await handler.process_turn(
                call_id=CALL_ID,
                user_text="okay",
                agent_text="I can book a call for you — would that work?",
                org_id=ORG_ID,
                lead_id=None,
                lead_email="",
                lead_name="Test Lead",
            )

        assert result.consumed
        assert "email" in (result.speak_override or "").lower()
        saved: BookingState = mem.save.call_args[0][1]
        assert saved.phase == PHASE_ASKING_EMAIL


# ---------------------------------------------------------------------------
# Scenario: _send_confirmation email validation
# ---------------------------------------------------------------------------


class TestSendConfirmation:
    @pytest.mark.asyncio
    async def test_skips_send_when_email_invalid(self):
        """_send_confirmation must NOT call send_meeting_confirmation for an invalid email."""
        state = _make_state(lead_email="not-valid")
        handler, _, _ = _make_handler(memory_state=state)
        event = _make_booked_event()

        send_mock = AsyncMock()
        # Patch the function at the module where it is defined; _send_confirmation
        # imports it locally via `from common.email.meeting_confirmation import ...`
        with (
            patch("modules.ai.booking_handler.SessionLocal"),
            patch("common.email.meeting_confirmation.send_meeting_confirmation", send_mock),
        ):
            await handler._send_confirmation(state, event)

        # No call may have targeted the invalid email address
        for call in send_mock.call_args_list:
            assert call.kwargs.get("to_email") != "not-valid"

    @pytest.mark.asyncio
    async def test_sends_to_valid_email(self):
        state = _make_state(lead_email="lead@example.com")
        handler, _, _ = _make_handler(memory_state=state)
        event = _make_booked_event()

        send_mock = AsyncMock()
        with (
            patch("modules.ai.booking_handler.SessionLocal"),
            patch("common.email.meeting_confirmation.send_meeting_confirmation", send_mock),
        ):
            await handler._send_confirmation(state, event)

        # At least one call must target the lead's email
        emails = [c.kwargs.get("to_email") for c in send_mock.call_args_list]
        assert "lead@example.com" in emails
