#!/usr/bin/env python3
"""Simulate the call booking conversation with real parsing + availability APIs.

Default mode is safe:
* Uses the real OpenAI client for booking intent and time extraction.
* Uses the real Google Calendar FreeBusy API for availability.
* Does NOT create a calendar event or send confirmation email.

Run from the backend directory:
    python scripts/simulate_booking_conversation.py --timezone Asia/Kolkata

To intentionally create a real calendar event, pass --live-book.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database.models  # noqa: F401 - register ORM models
from database.session import SessionLocal
from modules.ai.booking_handler import BookingHandler
from modules.ai.booking_state import BookingState
from modules.ai.dependencies import get_openai, shutdown_ai
from modules.calendar.dependencies import get_calendar_service
from modules.calendar.model import CalendarIntegration
from modules.calendar.schema import BookedEvent


@dataclass
class InMemoryBookingMemory:
    state: BookingState = field(default_factory=BookingState)

    async def get(self, call_id: str) -> BookingState:
        self.state.call_id = call_id
        return self.state

    async def save(self, call_id: str, state: BookingState) -> None:
        self.state = state

    async def clear(self, call_id: str) -> None:
        self.state = BookingState(call_id=call_id)


class SafeCalendarService:
    """Delegate availability to the real service; dry-run event creation."""

    def __init__(self, delegate, *, live_book: bool) -> None:
        self._delegate = delegate
        self._live_book = live_book
        self.book_attempts: list[dict[str, Any]] = []

    def get_integration(self, db, org_id):
        return self._delegate.get_integration(db, org_id)

    async def is_slot_available(self, db, **kwargs):
        return await self._delegate.is_slot_available(db, **kwargs)

    async def get_free_slots(self, db, **kwargs):
        return await self._delegate.get_free_slots(db, **kwargs)

    async def book_meeting(self, db, **kwargs):
        self.book_attempts.append(dict(kwargs))
        if self._live_book:
            return await self._delegate.book_meeting(db, **kwargs)

        start = kwargs["start"]
        duration = kwargs.get("duration_minutes", 30)
        end = start + timedelta(minutes=duration)
        tz_name = kwargs.get("timezone") or "UTC"
        try:
            local = start.astimezone(zoneinfo.ZoneInfo(tz_name))
        except Exception:
            local = start.astimezone(timezone.utc)

        return BookedEvent(
            event_id=f"dry-run-{uuid.uuid4()}",
            meet_link=None,
            html_link="dry-run://calendar-event-not-created",
            start_iso=start.astimezone(timezone.utc).isoformat(),
            end_iso=end.astimezone(timezone.utc).isoformat(),
            start_display=local.strftime("%-I:%M %p, %B %-d"),
            title=kwargs.get("title") or "Meeting",
        )


class SafeBookingHandler(BookingHandler):
    async def _send_confirmation(self, state, event) -> None:
        return None

    async def _log_activity(self, state, event) -> None:
        return None


def _parse_uuid(value: str | None, *, label: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise SystemExit(f"{label} must be a UUID, got: {value}") from exc


def _find_org_id(db, org_arg: uuid.UUID | None) -> uuid.UUID:
    if org_arg:
        return org_arg
    row = (
        db.query(CalendarIntegration)
        .filter_by(provider="google")
        .order_by(CalendarIntegration.created_at.desc())
        .first()
    )
    if row is None:
        raise SystemExit("No Google calendar integration found. Pass --org-id after connecting a calendar.")
    return row.organization_id


def _print_turn(label: str, user_text: str, speak: str | None, state: BookingState) -> None:
    print(f"\n{label}")
    print(f'User:  "{user_text}"')
    print(f'Agent: "{speak or "(no booking override)"}"')
    print(f"Phase: {state.phase}")
    if state.parsed_dt:
        print(f"Parsed slot UTC: {state.parsed_dt}")


async def _run(args: argparse.Namespace) -> int:
    org_arg = _parse_uuid(args.org_id, label="--org-id")
    db = SessionLocal()
    try:
        org_id = _find_org_id(db, org_arg)
    finally:
        db.close()

    call_id = f"booking-sim-{uuid.uuid4()}"
    memory = InMemoryBookingMemory()
    calendar = SafeCalendarService(get_calendar_service(), live_book=args.live_book)
    handler = SafeBookingHandler(
        calendar_svc=calendar,
        booking_memory=memory,
        openai_client=get_openai(),
    )

    print("\nBooking conversation simulation")
    print("=" * 31)
    print(f"Org: {org_id}")
    print(f"Timezone sent to BookingHandler: {args.timezone}")
    print(f"Lead email: {args.lead_email}")
    print(f"Slot request: {args.slot_text}")
    print(f"Live booking: {'YES - real event may be created' if args.live_book else 'NO - dry-run event only'}")

    first = await handler.process_turn(
        call_id=call_id,
        user_text=args.intent_text,
        agent_text=args.previous_agent_text,
        org_id=org_id,
        lead_id=None,
        lead_email=args.lead_email,
        lead_name=args.lead_name,
        timezone=args.timezone,
        duration_minutes=args.duration_minutes,
    )
    _print_turn("Turn 1 - booking intent", args.intent_text, first.speak_override, memory.state)

    second = await handler.process_turn(
        call_id=call_id,
        user_text=args.slot_text,
        agent_text=first.speak_override or "",
        org_id=org_id,
        lead_id=None,
        lead_email=args.lead_email,
        lead_name=args.lead_name,
        timezone=args.timezone,
        duration_minutes=args.duration_minutes,
    )
    _print_turn("Turn 2 - requested slot", args.slot_text, second.speak_override, memory.state)

    print("\nCalendar API result")
    print(f"Book attempted: {'yes' if calendar.book_attempts else 'no'}")
    if calendar.book_attempts:
        attempt = calendar.book_attempts[-1]
        print(f"Book start UTC: {attempt['start'].astimezone(timezone.utc).isoformat()}")
        print(f"Book timezone: {attempt.get('timezone')}")
        print(f"Meeting booked flag: {second.meeting_booked}")
        if not args.live_book:
            print("Dry-run: no calendar event was created and no email was sent.")

    await shutdown_ai()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate booking conversation with real APIs.")
    parser.add_argument("--org-id", help="Organization UUID. Defaults to latest connected Google calendar org.")
    parser.add_argument("--timezone", default="Asia/Kolkata", help="IANA timezone passed from campaign/call context.")
    parser.add_argument("--lead-email", default="qa@example.com", help="Lead email used by booking flow.")
    parser.add_argument("--lead-name", default="QA Lead", help="Lead name used by booking flow.")
    parser.add_argument("--duration-minutes", type=int, default=30)
    parser.add_argument("--intent-text", default="I want to book a meeting")
    parser.add_argument("--slot-text", default="tomorrow at 3 PM")
    parser.add_argument(
        "--previous-agent-text",
        default="I can help schedule a meeting with our team.",
        help="Previous agent message for context-aware intent detection.",
    )
    parser.add_argument(
        "--live-book",
        action="store_true",
        help="Actually create the calendar event and send confirmation email.",
    )
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
