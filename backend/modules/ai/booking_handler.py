"""Multi-turn booking state machine wired into the conversation orchestrator.

Flow
----
1.  Every turn (while phase=idle): detect_booking_intent on user_text.
    Context-aware: if the agent's last reply offered a meeting and the user
    replies with a simple confirmation ("yes", "sure", "okay"), that is also
    treated as booking intent.
    If intent detected → check calendar connectivity.
    - No calendar connected → surface spoken error, stay idle.
    - Calendar connected, email known → phase=asking_time.
    - Calendar connected, email missing → phase=asking_email.

2.  phase=asking_email: agent asked for the lead's email address.
    - Valid email parsed → store, phase=asking_time.
    - Invalid / unparseable → retry up to MAX_EMAIL_ATTEMPTS times, then fail.

3.  phase=asking_time: extract_slot_preference from user_text.
    a. type="specific":
       - Check if slot is available.
       - Available  → book it → send email → phase=booked, speak confirmation.
       - Unavailable → fetch 3 alternatives → phase=suggesting, speak alternatives.
    b. type="flexible":
       - Fetch 3 free slots, pick the first.
       - Confirm verbally → phase=confirming.

4.  phase=confirming: wait for lead's confirmation ("yes", "sounds good", etc.)
    - Confirmed → book it → send email → phase=booked.
    - Declined / different time → re-enter asking_time.

5.  phase=suggesting: lead picks a slot.
    - Parse their choice → book it → send email → phase=booked.

All returned ``speak_override`` values are short, voice-friendly sentences
(no URLs, no markdown — spoken aloud over the phone immediately).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from common.logging import get_logger
from database.session import SessionLocal
from modules.ai.booking_intents import detect_booking_intent, extract_slot_preference
from modules.ai.booking_state import (
    PHASE_ASKING_EMAIL,
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
    CalendarError,
    NoCalendarError,
)
from modules.calendar.schema import FreeSlot
from modules.calendar.service import CalendarService

log = get_logger("ai.booking_handler")

# Maximum times we re-ask for email before giving up
_MAX_EMAIL_ATTEMPTS = 3

# RFC-5322-lite email pattern — good enough for voice-collected addresses
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_CONFIRM_WORDS = {
    "yes", "yeah", "yep", "sure", "ok", "okay", "perfect",
    "that works", "sounds good", "works for me", "go ahead",
    "book it", "great", "let's do it", "confirmed", "fine",
    "absolutely", "definitely", "of course", "please do",
}

# Phrases that indicate the agent offered a meeting in its last turn
_MEETING_OFFER_PHRASES = (
    "schedule", "book a meeting", "book a call", "book a demo",
    "set up a meeting", "set up a call", "calendar invite",
    "find a time", "block time", "would you like to meet",
    "arrange a meeting", "get you on the calendar",
)


def _is_confirmation(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in _CONFIRM_WORDS)


def _agent_offered_meeting(agent_text: str) -> bool:
    """Return True if the agent's previous reply offered to schedule a meeting."""
    t = agent_text.lower()
    return any(phrase in t for phrase in _MEETING_OFFER_PHRASES)


def _extract_email(text: str) -> Optional[str]:
    """Pull the first email-shaped substring from transcribed speech."""
    m = _EMAIL_RE.search(text)
    return m.group(0).lower() if m else None


def _is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.fullmatch(email))


def _format_slot_list(slots: list[FreeSlot]) -> str:
    """Convert a list of slots to a voice-friendly spoken list."""
    if not slots:
        return "no available slots"
    if len(slots) == 1:
        return slots[0].start_display
    parts = [s.start_display for s in slots]
    return ", ".join(parts[:-1]) + f", or {parts[-1]}"


def _parse_dt(iso: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _is_past_slot(start: datetime) -> bool:
    return start.astimezone(timezone.utc) <= datetime.now(timezone.utc)


def _today_in_timezone(tz_name: str, *, _now: Optional[datetime] = None) -> str:
    """Return today's date string (YYYY-MM-DD) in the lead's local timezone.

    Using the lead's timezone matters: if the lead is in IST (UTC+5:30) and
    it's 23:00 UTC, "today" for the lead is already tomorrow.  Passing the
    wrong date makes the LLM mis-interpret relative expressions like "tomorrow".
    Falls back to UTC if the timezone is invalid.

    ``_now`` is accepted for testing — pass a known UTC datetime to make the
    result deterministic without patching the datetime class itself.
    """
    now_utc = _now if _now is not None else datetime.now(timezone.utc)
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
        return now_utc.astimezone(tz).strftime("%Y-%m-%d")
    except Exception:
        return now_utc.astimezone(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


@dataclass
class BookingTurnResult:
    """What BookingHandler.process_turn returns to the orchestrator."""

    # If set, the orchestrator speaks this instead of the GPT-4o reply.
    speak_override: Optional[str] = None
    # True when a meeting was just successfully booked this turn.
    meeting_booked: bool = False
    meet_link: Optional[str] = None
    booked_start_display: Optional[str] = None
    # Whether the booking phase consumed this turn (skip normal GPT processing)
    consumed: bool = False


# ---------------------------------------------------------------------------
# BookingHandler
# ---------------------------------------------------------------------------


class BookingHandler:
    """Per-call booking state machine. Thread-safe (one instance per process,
    stateless except for Redis-backed BookingState)."""

    def __init__(
        self,
        *,
        calendar_svc: CalendarService,
        booking_memory: BookingMemory,
        openai_client,
    ) -> None:
        self._cal = calendar_svc
        self._mem = booking_memory
        self._openai = openai_client

    # ------------------------------------------------------------------
    # Main entry point (called from orchestrator after every user turn)
    # ------------------------------------------------------------------

    async def process_turn(
        self,
        *,
        call_id: str,
        user_text: str,
        agent_text: str,
        org_id: Optional[uuid.UUID],
        lead_id: Optional[uuid.UUID],
        lead_email: str,
        lead_name: str,
        timezone: str = "UTC",
        duration_minutes: int = 30,
    ) -> BookingTurnResult:
        if not org_id:
            return BookingTurnResult()

        state = await self._mem.get(call_id)

        # Seed persistent fields on first touch
        if not state.lead_email and lead_email:
            state.lead_email = lead_email
        if not state.lead_name and lead_name:
            state.lead_name = lead_name
        if not state.org_id:
            state.org_id = str(org_id)
        state.call_id = call_id
        state.timezone = timezone or state.timezone or "UTC"
        state.duration_minutes = duration_minutes

        # Terminal phases are no-ops
        if state.phase in {PHASE_BOOKED, PHASE_FAILED}:
            return BookingTurnResult(meeting_booked=(state.phase == PHASE_BOOKED))

        # Dispatch — idle and asking_email get extra context args
        if state.phase == PHASE_IDLE:
            result = await self._handle_idle(state, user_text=user_text, agent_text=agent_text)
        elif state.phase == PHASE_ASKING_EMAIL:
            result = await self._handle_asking_email(state, user_text=user_text)
        else:
            handler = {
                PHASE_ASKING_TIME: self._handle_asking_time,
                PHASE_CONFIRMING: self._handle_confirming,
                PHASE_SUGGESTING: self._handle_suggesting,
            }.get(state.phase)
            if handler is None:
                return BookingTurnResult()
            result = await handler(state, user_text=user_text)

        await self._mem.save(call_id, state)
        return result

    # ------------------------------------------------------------------
    # Phase handlers
    # ------------------------------------------------------------------

    async def _handle_idle(
        self, state: BookingState, *, user_text: str, agent_text: str = ""
    ) -> BookingTurnResult:
        # Context-aware: if the agent offered a meeting and the user confirmed,
        # treat that as booking intent without an extra LLM call.
        if agent_text and _agent_offered_meeting(agent_text) and _is_confirmation(user_text):
            intent = "book"
            log.info(
                "booking.INTENT_DETECTED_CONTEXT_AWARE",
                call_id=state.call_id,
                user_text=user_text,
            )
        else:
            intent = await detect_booking_intent(user_text, self._openai)

        if intent != "book":
            return BookingTurnResult()

        log.info("booking.INTENT_DETECTED", call_id=state.call_id, user_text=user_text)

        # Verify the calendar integration is reachable before entering the flow
        db = SessionLocal()
        try:
            self._cal.get_integration(db, state.org_id if state.org_id else None)  # type: ignore[arg-type]
        except NoCalendarError:
            log.warning(
                "booking.NO_CALENDAR_CONNECTED",
                call_id=state.call_id,
                org_id=state.org_id,
            )
            return BookingTurnResult(
                speak_override=(
                    "I'd love to schedule a meeting, but our calendar isn't set up yet. "
                    "Someone from our team will reach out to find a time that works."
                ),
                consumed=True,
            )
        except CalendarAuthError:
            log.warning(
                "booking.CALENDAR_AUTH_ERROR",
                call_id=state.call_id,
                org_id=state.org_id,
            )
            return BookingTurnResult(
                speak_override=(
                    "I'm having trouble accessing our calendar right now. "
                    "Our team will follow up to get something scheduled."
                ),
                consumed=True,
            )
        except Exception as exc:
            log.warning(
                "booking.calendar_check_failed",
                call_id=state.call_id,
                error=str(exc),
            )
            return BookingTurnResult()
        finally:
            db.close()

        # If we don't have the lead's email, collect it before asking for a time
        if not state.lead_email:
            state.phase = PHASE_ASKING_EMAIL
            log.info("booking.ASKING_EMAIL", call_id=state.call_id)
            return BookingTurnResult(
                speak_override=(
                    "I'd be happy to schedule that. "
                    "Could you give me your email address so I can send you the calendar invite?"
                ),
                consumed=True,
            )

        state.phase = PHASE_ASKING_TIME
        return BookingTurnResult(
            speak_override="Great! What date and time works best for you?",
            consumed=True,
        )

    async def _handle_asking_email(
        self, state: BookingState, *, user_text: str
    ) -> BookingTurnResult:
        """Collect and validate the lead's email address before booking."""
        email = _extract_email(user_text)

        if email and _is_valid_email(email):
            state.lead_email = email
            state.email_attempts = 0
            state.phase = PHASE_ASKING_TIME
            log.info(
                "booking.EMAIL_COLLECTED",
                call_id=state.call_id,
                email=email,
            )
            return BookingTurnResult(
                speak_override="Thanks! What date and time works best for you?",
                consumed=True,
            )

        state.email_attempts += 1
        log.info(
            "booking.email_attempt_failed",
            call_id=state.call_id,
            attempt=state.email_attempts,
            user_text=user_text,
        )

        if state.email_attempts >= _MAX_EMAIL_ATTEMPTS:
            state.phase = PHASE_FAILED
            log.warning(
                "booking.EMAIL_COLLECTION_EXHAUSTED",
                call_id=state.call_id,
            )
            return BookingTurnResult(
                speak_override=(
                    "No worries — someone from our team will follow up "
                    "to get a meeting scheduled with you."
                ),
                consumed=True,
            )

        prompt = (
            "I didn't quite catch that. Could you spell out your email address for me?"
            if state.email_attempts == 1
            else "I'm having trouble getting that. Could you say your email one more time, slowly?"
        )
        return BookingTurnResult(speak_override=prompt, consumed=True)

    async def _handle_asking_time(self, state: BookingState, *, user_text: str) -> BookingTurnResult:
        today_iso = _today_in_timezone(state.timezone)
        log.info(
            "booking.ASKING_TIME_PROCESSING",
            call_id=state.call_id,
            user_text=user_text,
            timezone=state.timezone,
            today_iso=today_iso,
            duration_minutes=state.duration_minutes,
        )
        pref = await extract_slot_preference(
            user_text,
            today_iso=today_iso,
            timezone_name=state.timezone,
            openai_client=self._openai,
        )
        state.preferred_raw = pref.raw
        log.info(
            "booking.SLOT_PREFERENCE_EXTRACTED",
            call_id=state.call_id,
            pref_type=pref.type,
            pref_raw=pref.raw,
            parsed_dt=pref.parsed_dt,
            timezone=state.timezone,
            today_iso=today_iso,
        )

        if pref.type == "flexible":
            log.info("booking.FLEXIBLE_SLOT_REQUESTED", call_id=state.call_id)
            return await self._pick_and_confirm(state)

        if pref.type == "specific" and pref.parsed_dt:
            state.parsed_dt = pref.parsed_dt
            start = _parse_dt(pref.parsed_dt)
            log.info(
                "booking.SPECIFIC_SLOT_PARSED",
                call_id=state.call_id,
                parsed_dt_raw=pref.parsed_dt,
                parsed_dt_object=str(start),
                start_tzinfo=str(start.tzinfo) if start else None,
            )
            if start is None:
                log.warning(
                    "booking.SLOT_PARSE_FAILED",
                    call_id=state.call_id,
                    parsed_dt_raw=pref.parsed_dt,
                )
                return BookingTurnResult(
                    speak_override="Sorry, I didn't catch that time. Could you tell me what day and time works for you?",
                    consumed=True,
                )
            if _is_past_slot(start):
                log.warning(
                    "booking.PAST_SLOT_REJECTED",
                    call_id=state.call_id,
                    parsed_dt_raw=pref.parsed_dt,
                    parsed_dt_object=start.isoformat(),
                    timezone=state.timezone,
                )
                return BookingTurnResult(
                    speak_override=(
                        "That time has already passed. "
                        "Could you tell me a future day and time that works?"
                    ),
                    consumed=True,
                )
            return await self._check_and_book_or_suggest(state, start)

        # Unclear — ask again
        log.info(
            "booking.SLOT_PREFERENCE_UNCLEAR",
            call_id=state.call_id,
            pref_type=pref.type,
            pref_raw=pref.raw,
            user_text=user_text,
        )
        return BookingTurnResult(
            speak_override="I didn't quite catch that. What day and time would you like to meet?",
            consumed=True,
        )

    async def _handle_confirming(self, state: BookingState, *, user_text: str) -> BookingTurnResult:
        if _is_confirmation(user_text):
            if not state.parsed_dt:
                # Edge case: no stored slot; re-ask
                state.phase = PHASE_ASKING_TIME
                return BookingTurnResult(
                    speak_override="What time would you like to schedule the meeting?",
                    consumed=True,
                )
            start = _parse_dt(state.parsed_dt)
            if start is None:
                state.phase = PHASE_ASKING_TIME
                return BookingTurnResult(
                    speak_override="Let me re-confirm — what day and time works for you?",
                    consumed=True,
                )
            if _is_past_slot(start):
                state.phase = PHASE_ASKING_TIME
                return BookingTurnResult(
                    speak_override=(
                        "That time has already passed. "
                        "Could you tell me a future day and time that works?"
                    ),
                    consumed=True,
                )
            return await self._do_book(state, start)
        else:
            # Lead said something else — go back to asking
            state.phase = PHASE_ASKING_TIME
            return BookingTurnResult(
                speak_override="No problem — what time would work better for you?",
                consumed=True,
            )

    async def _handle_suggesting(self, state: BookingState, *, user_text: str) -> BookingTurnResult:
        """Lead is choosing from the suggested alternatives."""
        today_iso = _today_in_timezone(state.timezone)
        pref = await extract_slot_preference(
            user_text,
            today_iso=today_iso,
            timezone_name=state.timezone,
            openai_client=self._openai,
        )

        if pref.type == "specific" and pref.parsed_dt:
            start = _parse_dt(pref.parsed_dt)
            if start:
                if _is_past_slot(start):
                    state.phase = PHASE_ASKING_TIME
                    return BookingTurnResult(
                        speak_override=(
                            "That time has already passed. "
                            "Could you tell me a future day and time that works?"
                        ),
                        consumed=True,
                    )
                state.parsed_dt = pref.parsed_dt
                return await self._check_and_book_or_suggest(state, start)

        # If the lead mentioned a slot index ("the first one", "second one")
        # or something we can't parse, just re-offer
        if state.suggested_slots:
            slot_list = _format_slot_list(
                [FreeSlot(**s) for s in state.suggested_slots]
            )
            return BookingTurnResult(
                speak_override=f"I have {slot_list} available. Which would you prefer?",
                consumed=True,
            )

        # Fall back to asking again
        state.phase = PHASE_ASKING_TIME
        return BookingTurnResult(
            speak_override="What time works best for you?",
            consumed=True,
        )

    # ------------------------------------------------------------------
    # Booking helpers
    # ------------------------------------------------------------------

    async def _pick_and_confirm(self, state: BookingState) -> BookingTurnResult:
        """Find earliest free slot and confirm verbally before booking."""
        today = datetime.now(timezone.utc).date()
        today_in_tz = _today_in_timezone(state.timezone)
        log.info(
            "booking.PICKING_FREE_SLOT",
            call_id=state.call_id,
            target_date_utc=str(today),
            target_date_in_lead_tz=today_in_tz,
            duration_minutes=state.duration_minutes,
            timezone=state.timezone,
            note="target_date uses UTC date — may differ from lead's local date",
        )
        db = SessionLocal()
        try:
            slots = await self._cal.get_free_slots(
                db,
                org_id=uuid.UUID(state.org_id),
                target_date=today,
                duration_minutes=state.duration_minutes,
                timezone=state.timezone,
                count=1,
            )
            log.info(
                "booking.FREE_SLOTS_RESULT",
                call_id=state.call_id,
                count=len(slots),
                target_date=str(today),
            )
        except (NoCalendarError, CalendarAuthError) as exc:
            log.warning(
                "booking.CALENDAR_UNAVAILABLE_PICK_SLOT",
                call_id=state.call_id,
                error=str(exc),
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I'm sorry, I lost access to our calendar. "
                    "Our team will follow up to get something booked."
                ),
                consumed=True,
            )
        except CalendarAPIError as exc:
            # Google API error — not a "no slots" situation; be explicit about the cause
            log.warning(
                "booking.CALENDAR_API_ERROR_PICK_SLOT",
                call_id=state.call_id,
                error=str(exc),
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I'm having trouble checking our calendar right now. "
                    "Someone from our team will follow up to find a good time."
                ),
                consumed=True,
            )
        except Exception as exc:
            log.error(
                "booking.PICK_SLOT_UNEXPECTED_ERROR",
                call_id=state.call_id,
                error=str(exc),
            )
            slots = []
        finally:
            db.close()

        if not slots:
            state.phase = PHASE_ASKING_TIME
            return BookingTurnResult(
                speak_override=(
                    "I don't see any openings today. "
                    "What day works for you and I'll check availability?"
                ),
                consumed=True,
            )

        best = slots[0]
        state.parsed_dt = best.start.isoformat()
        state.phase = PHASE_CONFIRMING
        log.info(
            "booking.SLOT_OFFERED_FOR_CONFIRMATION",
            call_id=state.call_id,
            slot=best.start.isoformat(),
            display=best.start_display,
        )
        return BookingTurnResult(
            speak_override=(
                f"I have an opening at {best.start_display}. "
                "Does that work for you?"
            ),
            consumed=True,
        )

    async def _check_and_book_or_suggest(
        self, state: BookingState, start: datetime
    ) -> BookingTurnResult:
        log.info(
            "booking.CHECKING_AVAILABILITY",
            call_id=state.call_id,
            org_id=state.org_id,
            start=start.isoformat(),
            start_tzinfo=str(start.tzinfo),
            duration_minutes=state.duration_minutes,
            lead_email=state.lead_email,
            timezone=state.timezone,
        )
        db = SessionLocal()
        try:
            available = await self._cal.is_slot_available(
                db,
                org_id=uuid.UUID(state.org_id),
                start=start,
                duration_minutes=state.duration_minutes,
            )
            log.info(
                "booking.AVAILABILITY_RESULT",
                call_id=state.call_id,
                org_id=state.org_id,
                start=start.isoformat(),
                available=available,
                decision=("WILL_BOOK" if available else "WILL_SUGGEST_ALTERNATIVES"),
            )
        except (NoCalendarError, CalendarAuthError) as exc:
            log.warning(
                "booking.CALENDAR_UNAVAILABLE_AVAILABILITY_CHECK",
                call_id=state.call_id,
                error=str(exc),
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I'm sorry, I lost access to our calendar. "
                    "Our team will follow up to get something booked."
                ),
                consumed=True,
            )
        except CalendarAPIError as exc:
            # Google API returned an error — this is NOT a "slot is busy" signal.
            # Never default available=False here; surface the real problem to the caller.
            log.warning(
                "booking.CALENDAR_API_ERROR_AVAILABILITY_CHECK",
                call_id=state.call_id,
                start=start.isoformat(),
                error=str(exc),
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I'm having trouble checking that time right now — "
                    "our calendar service isn't responding. "
                    "Someone from our team will follow up to confirm a slot."
                ),
                consumed=True,
            )
        except Exception as exc:
            log.error(
                "booking.AVAILABILITY_CHECK_UNEXPECTED_ERROR",
                call_id=state.call_id,
                start=start.isoformat(),
                error=str(exc),
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I ran into an unexpected issue checking availability. "
                    "Our team will reach out to schedule a time."
                ),
                consumed=True,
            )
        finally:
            db.close()

        if available:
            return await self._do_book(state, start)

        # Slot is genuinely busy — find alternatives on the same day
        log.info(
            "booking.SLOT_BUSY_FINDING_ALTERNATIVES",
            call_id=state.call_id,
            start=start.isoformat(),
        )
        db = SessionLocal()
        try:
            alternatives = await self._cal.get_free_slots(
                db,
                org_id=uuid.UUID(state.org_id),
                target_date=start.astimezone(timezone.utc).date(),
                duration_minutes=state.duration_minutes,
                timezone=state.timezone,
                count=3,
            )
            log.info(
                "booking.ALTERNATIVES_FOUND",
                call_id=state.call_id,
                count=len(alternatives),
            )
        except (NoCalendarError, CalendarAuthError) as exc:
            log.warning(
                "booking.CALENDAR_UNAVAILABLE_ALTERNATIVES",
                call_id=state.call_id,
                error=str(exc),
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I'm sorry, I can't check alternative times right now. "
                    "Our team will follow up with some options."
                ),
                consumed=True,
            )
        except CalendarAPIError as exc:
            log.warning(
                "booking.CALENDAR_API_ERROR_ALTERNATIVES",
                call_id=state.call_id,
                error=str(exc),
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "That time isn't available, and I'm having trouble fetching alternatives. "
                    "Someone from our team will follow up with some options."
                ),
                consumed=True,
            )
        except Exception as exc:
            # Do NOT silently set alternatives=[] here — that would produce a
            # false "That time is fully booked" message when the real cause is
            # an unrelated runtime error.  Surface the actual problem instead.
            log.error(
                "booking.ALTERNATIVES_UNEXPECTED_ERROR",
                call_id=state.call_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I ran into an unexpected issue finding alternative times. "
                    "Our team will reach out to schedule something."
                ),
                consumed=True,
            )
        finally:
            db.close()

        if not alternatives:
            state.phase = PHASE_ASKING_TIME
            return BookingTurnResult(
                speak_override=(
                    "That time is fully booked and I don't see other openings that day. "
                    "What other day works for you?"
                ),
                consumed=True,
            )

        state.phase = PHASE_SUGGESTING
        state.suggested_slots = [s.model_dump(mode="json") for s in alternatives]
        slot_list = _format_slot_list(alternatives)
        return BookingTurnResult(
            speak_override=(
                f"That time is taken. I have {slot_list} available. "
                "Which works best for you?"
            ),
            consumed=True,
        )

    async def _do_book(self, state: BookingState, start: datetime) -> BookingTurnResult:
        """Create the Google Calendar event and send the confirmation email."""

        if _is_past_slot(start):
            state.phase = PHASE_ASKING_TIME
            log.warning(
                "booking.PAST_SLOT_BOOK_REJECTED",
                call_id=state.call_id,
                start=start.isoformat(),
                timezone=state.timezone,
            )
            return BookingTurnResult(
                speak_override=(
                    "That time has already passed. "
                    "Could you tell me a future day and time that works?"
                ),
                consumed=True,
            )

        # Guard: email must be present and valid before hitting the API
        if not state.lead_email or not _is_valid_email(state.lead_email):
            log.warning(
                "booking.EMAIL_MISSING_AT_BOOK",
                call_id=state.call_id,
                lead_email=repr(state.lead_email),
            )
            # Store the confirmed slot so we can book right after collecting email
            state.parsed_dt = start.isoformat()
            state.phase = PHASE_ASKING_EMAIL
            return BookingTurnResult(
                speak_override=(
                    "Before I confirm, could you give me your email address "
                    "so I can send you the calendar invite?"
                ),
                consumed=True,
            )

        log.info(
            "booking.ATTEMPTING_BOOK",
            call_id=state.call_id,
            org_id=state.org_id,
            lead_email=state.lead_email,
            lead_name=state.lead_name,
            start=start.isoformat(),
            start_tzinfo=str(start.tzinfo),
            duration_minutes=state.duration_minutes,
            timezone=state.timezone,
        )
        db = SessionLocal()
        try:
            event = await self._cal.book_meeting(
                db,
                org_id=uuid.UUID(state.org_id),
                start=start,
                duration_minutes=state.duration_minutes,
                title="Meeting",
                description=f"Meeting booked via AI call with {state.lead_name}.",
                attendee_email=state.lead_email,
                attendee_name=state.lead_name,
                timezone=state.timezone,
            )
        except (NoCalendarError, CalendarAuthError) as exc:
            log.warning(
                "booking.CALENDAR_UNAVAILABLE_AT_BOOK",
                call_id=state.call_id,
                error=str(exc),
                org_id=state.org_id,
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I'm sorry — our calendar isn't reachable right now. "
                    "Someone from our team will follow up with a calendar invite."
                ),
                consumed=True,
            )
        except CalendarError as exc:
            log.warning(
                "booking.BOOK_FAILED",
                call_id=state.call_id,
                error=exc.message,
                org_id=state.org_id,
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I wasn't able to complete the booking on my end. "
                    "Someone from our team will follow up with a calendar invite."
                ),
                consumed=True,
            )
        except Exception as exc:
            log.warning(
                "booking.BOOK_EXCEPTION",
                call_id=state.call_id,
                error=str(exc),
                org_id=state.org_id,
            )
            state.phase = PHASE_FAILED
            return BookingTurnResult(
                speak_override=(
                    "I ran into a technical issue booking the meeting. "
                    "Our team will send you a calendar invite shortly."
                ),
                consumed=True,
            )
        finally:
            db.close()

        state.phase = PHASE_BOOKED
        state.booked_event_id = event.event_id
        state.meet_link = event.meet_link
        state.booked_start_display = event.start_display
        state.html_link = event.html_link

        log.info(
            "booking.MEETING_BOOKED",
            call_id=state.call_id,
            event_id=event.event_id,
            meet_link=event.meet_link,
            html_link=event.html_link,
            start_display=event.start_display,
            start_iso=event.start_iso,
            lead_email=state.lead_email,
            lead_name=state.lead_name,
            org_id=state.org_id,
            duration_minutes=state.duration_minutes,
        )

        # Send confirmation email — awaited directly so it completes before
        # the call continues (avoids task being dropped on event loop shutdown).
        log.info(
            "booking.SENDING_INVITE",
            call_id=state.call_id,
            lead_email=state.lead_email,
        )
        await self._send_confirmation(state, event)

        # Log activity fire-and-forget (non-critical, DB write)
        asyncio.create_task(
            self._log_activity(state, event),
            name=f"booking-activity:{state.call_id}",
        )

        confirmation = (
            f"Your meeting has been booked for {event.start_display}. "
        )
        if event.meet_link:
            confirmation += "I've sent a calendar invitation with the Google Meet link to your email."
        else:
            confirmation += "A calendar invitation has been sent to your email."

        return BookingTurnResult(
            speak_override=confirmation,
            meeting_booked=True,
            meet_link=event.meet_link,
            booked_start_display=event.start_display,
            consumed=True,
        )

    # ------------------------------------------------------------------
    # Side-effects (fire-and-forget)
    # ------------------------------------------------------------------

    async def _send_confirmation(self, state: BookingState, event) -> None:
        from common.email.meeting_confirmation import send_meeting_confirmation

        start = _parse_dt(event.start_iso) if event.start_iso else None
        meet_link = event.meet_link or event.html_link

        # Email to the lead
        if state.lead_email and _is_valid_email(state.lead_email):
            try:
                await send_meeting_confirmation(
                    to_email=state.lead_email,
                    to_name=state.lead_name,
                    slot=start,
                    meet_link=meet_link,
                    organizer_name="Our Team",
                    timezone=state.timezone,
                    duration_minutes=state.duration_minutes,
                )
                log.info(
                    "booking.LEAD_INVITE_SENT",
                    call_id=state.call_id,
                    lead_email=state.lead_email,
                )
            except Exception as exc:
                log.warning(
                    "booking.LEAD_INVITE_FAILED",
                    call_id=state.call_id,
                    lead_email=state.lead_email,
                    error=str(exc),
                )
        else:
            log.warning(
                "booking.LEAD_INVITE_SKIPPED_NO_EMAIL",
                call_id=state.call_id,
                lead_email=repr(state.lead_email),
            )

        # Email to the organizer (calendar owner) if different from the lead
        organizer_email = getattr(event, "organizer_email", None)
        if not organizer_email:
            # Try to get from the calendar integration row
            try:
                from modules.calendar.model import CalendarIntegration
                db = SessionLocal()
                try:
                    row = db.query(CalendarIntegration).filter_by(
                        organization_id=uuid.UUID(state.org_id), provider="google"
                    ).first()
                    if row:
                        organizer_email = row.calendar_email
                finally:
                    db.close()
            except Exception:
                pass

        if organizer_email and organizer_email != state.lead_email:
            try:
                await send_meeting_confirmation(
                    to_email=organizer_email,
                    to_name="Team",
                    slot=start,
                    meet_link=meet_link,
                    organizer_name="Aifficient AI",
                    timezone=state.timezone,
                    duration_minutes=state.duration_minutes,
                )
                log.info(
                    "booking.ORGANIZER_INVITE_SENT",
                    call_id=state.call_id,
                    organizer_email=organizer_email,
                )
            except Exception as exc:
                log.warning(
                    "booking.ORGANIZER_INVITE_FAILED",
                    call_id=state.call_id,
                    organizer_email=organizer_email,
                    error=str(exc),
                )

    async def _log_activity(self, state: BookingState, event) -> None:
        try:
            import asyncio as _asyncio
            await _asyncio.to_thread(
                self._log_activity_sync, state, event
            )
        except Exception as exc:
            log.warning("booking.activity_log_failed", call_id=state.call_id, error=str(exc))

    @staticmethod
    def _log_activity_sync(state: BookingState, event) -> None:
        from database.session import SessionLocal
        from modules.leads.model import LeadActivity

        if not state.org_id:
            return

        db = SessionLocal()
        try:
            org_uuid = uuid.UUID(state.org_id)
            notes_data = {
                "event_id": event.event_id,
                "meet_link": event.meet_link,
                "start_display": event.start_display,
                "start_iso": event.start_iso,
                "call_id": state.call_id,
            }
            # lead_id is optional — only set when a real UUID was passed
            lead_uuid: uuid.UUID | None = None
            if state.call_id:
                try:
                    # The call_id may be a UUID when the AI call row was
                    # seeded with the lead's id (telephony path). Best-effort.
                    potential = uuid.UUID(state.call_id)
                    # Validate it actually exists in leads table
                    from modules.leads.model import Lead
                    if db.get(Lead, potential) is not None:
                        lead_uuid = potential
                except (ValueError, Exception):
                    pass

            activity = LeadActivity(
                organization_id=org_uuid,
                lead_id=lead_uuid,
                activity_type="mtg_booked",  # ≤16 chars per DB constraint
                notes=json.dumps(notes_data),
            )
            db.add(activity)
            db.commit()
        except Exception as exc:
            log.warning("booking.activity_sync_failed", error=str(exc))
            db.rollback()
        finally:
            db.close()
