"""Booking session state — persisted in Redis alongside conversation memory.

Redis key: ``ai:booking:{call_id}``  (same TTL as the call's memory keys)

Phases
------
idle                — no booking intent detected yet
asking_email        — agent asked for lead's email address; waiting for reply
asking_time         — agent asked "what time works?"; waiting for lead's answer
checking            — (transitional) slot check in flight
confirming          — agent confirmed a slot verbally; waiting for lead's "yes"
suggesting          — slot unavailable; agent offered alternatives; waiting for pick
booked              — meeting successfully created; terminal
failed              — booking attempt failed (terminal, surfaces fallback message)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from redis import asyncio as aioredis

from common.logging import get_logger
from config.settings import settings

log = get_logger("ai.booking_state")

PHASE_IDLE = "idle"
PHASE_ASKING_EMAIL = "asking_email"
PHASE_ASKING_TIME = "asking_time"
PHASE_CHECKING = "checking"
PHASE_CONFIRMING = "confirming"
PHASE_SUGGESTING = "suggesting"
PHASE_BOOKED = "booked"
PHASE_FAILED = "failed"

TERMINAL_PHASES = {PHASE_BOOKED, PHASE_FAILED}


def _key(call_id: str) -> str:
    return f"ai:booking:{call_id}"


@dataclass
class BookingState:
    phase: str = PHASE_IDLE
    lead_email: str = ""
    lead_name: str = ""
    org_id: str = ""
    call_id: str = ""

    # What the lead said when asked for a time
    preferred_raw: str = ""
    # Parsed preferred datetime in ISO8601 UTC
    parsed_dt: Optional[str] = None

    # Requested duration for this booking
    duration_minutes: int = 30
    # Prospect's stated timezone
    timezone: str = "UTC"

    # Slots offered when requested slot is unavailable
    suggested_slots: list[dict] = field(default_factory=list)

    # Tracks failed email collection attempts before giving up
    email_attempts: int = 0

    # Result of successful booking
    booked_event_id: Optional[str] = None
    meet_link: Optional[str] = None
    booked_start_display: Optional[str] = None
    html_link: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, blob: str) -> "BookingState":
        data = json.loads(blob)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class BookingMemory:
    """Async Redis facade for per-call booking state."""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._r: aioredis.Redis = client or aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        self._ttl = settings.AI_MEMORY_TTL_SECONDS

    async def get(self, call_id: str) -> BookingState:
        try:
            blob = await self._r.get(_key(call_id))
        except Exception:
            return BookingState(call_id=call_id)
        if not blob:
            return BookingState(call_id=call_id)
        try:
            return BookingState.from_json(blob)
        except Exception:
            return BookingState(call_id=call_id)

    async def save(self, call_id: str, state: BookingState) -> None:
        try:
            await self._r.set(_key(call_id), state.to_json(), ex=self._ttl)
        except Exception as exc:
            log.warning("booking_state.save_failed", call_id=call_id, error=str(exc))

    async def clear(self, call_id: str) -> None:
        try:
            await self._r.delete(_key(call_id))
        except Exception:
            pass
