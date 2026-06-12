"""GPT-4o function-call helpers for booking intent detection and slot extraction.

Two functions are exposed to the caller:

detect_booking_intent(user_text) → "book" | "none"
    Lightweight: only fires while booking phase == idle.  Costs one LLM call
    per user turn while idle but uses a tiny prompt and a JSON response_format
    so latency is well under 1 s on gpt-4o-mini / gpt-4o.

extract_slot_preference(user_text, today_iso, timezone) → SlotPreference
    Fired once when the agent has asked "what time works?" and the lead
    answers.  Handles phonetic transcripts ("three pee em", "tmrw", "next
    Friday"), relative expressions ("tomorrow", "in two hours"), and
    flexible replies ("any time", "you pick").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from common.logging import get_logger
from config.settings import settings
from modules.ai.schema import ChatMessage, MessageRole

log = get_logger("ai.booking_intents")


@dataclass
class SlotPreference:
    type: str  # "specific" | "flexible" | "unclear"
    parsed_dt: Optional[str] = None  # ISO8601 UTC or None
    raw: str = ""
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------


async def detect_booking_intent(user_text: str, openai_client) -> str:
    """Return "book" if the user clearly intends to schedule a meeting, else "none"."""

    prompt = (
        "The user said the following on a sales call. "
        "Does the user express clear intent to schedule a meeting, demo, or call? "
        'Respond ONLY with JSON: {"intent": "book"} or {"intent": "none"}.\n\n'
        f'User: "{user_text}"'
    )
    try:
        result = await openai_client.complete(
            [ChatMessage(role=MessageRole.USER, content=prompt)],
            temperature=0.0,
            max_tokens=20,
        )
        text = (result.text or "").strip()
        data = json.loads(text)
        return data.get("intent", "none")
    except Exception as exc:
        log.warning("booking_intents.detect_failed", error=str(exc))
        return "none"


# ---------------------------------------------------------------------------
# Slot extraction
# ---------------------------------------------------------------------------


async def extract_slot_preference(
    user_text: str,
    *,
    today_iso: str,
    timezone_name: str,
    openai_client,
) -> SlotPreference:
    """Parse the lead's time preference from their reply.

    ``today_iso`` must already be computed in the lead's local timezone so that
    relative expressions like "tomorrow" resolve correctly.
    ``timezone_name`` is the IANA timezone string (e.g. "Asia/Kolkata") used to
    convert the local time the user expresses into a UTC ISO8601 datetime.
    """
    # Produce a clear UTC-offset example for the prompt based on the timezone.
    tz_hint = f"IANA timezone {timezone_name}"

    prompt = (
        f"Today's date in the user's local timezone ({timezone_name}) is {today_iso}.\n"
        f"All times the user mentions are in their LOCAL timezone ({timezone_name}).\n"
        "Extract the meeting time the user has requested.\n\n"
        f'User said: "{user_text}"\n\n'
        "Rules:\n"
        '- If the user names a specific date/time, set type="specific" and convert '
        f"that local time to UTC ISO8601 (accounting for {tz_hint}).\n"
        f'- If the user says "tomorrow", use the calendar date one day after {today_iso}.\n'
        '- If the user says "any time", "you pick", "whenever", "flexible", set type="flexible".\n'
        '- If you cannot parse a time at all, set type="unclear".\n'
        "- NEVER assume UTC when the user gives a local time — always apply the "
        f"correct offset for {timezone_name}.\n\n"
        "Respond ONLY with valid JSON:\n"
        '{"type": "specific" | "flexible" | "unclear", '
        '"parsed_dt": "ISO8601 datetime in UTC, e.g. 2026-06-13T09:30:00+00:00, or null", '
        '"raw": "verbatim time the user said", '
        '"confidence": 0.0-1.0}'
    )
    try:
        result = await openai_client.complete(
            [ChatMessage(role=MessageRole.USER, content=prompt)],
            temperature=0.0,
            max_tokens=80,
        )
        text = (result.text or "").strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
        return SlotPreference(
            type=data.get("type", "unclear"),
            parsed_dt=data.get("parsed_dt"),
            raw=data.get("raw", user_text),
            confidence=float(data.get("confidence", 0.5)),
        )
    except Exception as exc:
        log.warning("booking_intents.extract_failed", error=str(exc))
        return SlotPreference(type="unclear", raw=user_text)
