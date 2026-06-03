"""Meeting booking *status tracking* — placeholder only.

This module deliberately implements **no** scheduling, calendar
integration, or booking workflow. It exists solely to track and report a
coarse meeting-intent status across a call so the conversation loop, the
logs, and the end-of-call summary can surface whether the lead agreed to
a meeting.

Status values
-------------
* ``unknown``     — call just started; no signal either way yet.
* ``not_booked``  — the conversation is underway but no agreement
  detected.
* ``booked``      — a successful meeting agreement was detected.

Detection is a lightweight, deterministic heuristic over the latest user
turn (and the agent's proposal). It is intentionally conservative: it
only promotes to ``booked`` when the lead clearly confirms in the context
of the agent proposing a time/meeting. Swap this for an LLM/tool call
when real booking lands — the call sites only depend on
:func:`detect_status` and the ``MEETING_STATUS_*`` constants.
"""

from __future__ import annotations

import re

MEETING_STATUS_UNKNOWN = "unknown"
MEETING_STATUS_NOT_BOOKED = "not_booked"
MEETING_STATUS_BOOKED = "booked"

VALID_STATUSES = (
    MEETING_STATUS_UNKNOWN,
    MEETING_STATUS_NOT_BOOKED,
    MEETING_STATUS_BOOKED,
)


# Phrases the lead might say to confirm a meeting. Matched on the user turn.
_CONFIRM_PATTERNS = [
    r"\byes\b",
    r"\byeah\b",
    r"\byep\b",
    r"\bsure\b",
    r"\bsounds good\b",
    r"\bthat works\b",
    r"\bworks for me\b",
    r"\blet'?s do\b",
    r"\blet'?s schedule\b",
    r"\bbook (it|me|that)\b",
    r"\bgo ahead\b",
    r"\bperfect\b",
    r"\bsee you (then|tomorrow|monday|tuesday|wednesday|thursday|friday)\b",
    r"\bi'?m (free|available)\b",
]

# Signals (from either side) that the conversation is actually about
# scheduling a meeting/time — required as context before a bare "yes" is
# treated as a booking confirmation.
_SCHEDULING_CONTEXT_PATTERNS = [
    r"\bmeeting\b",
    r"\bcall\b",
    r"\bdemo\b",
    r"\bwalkthrough\b",
    r"\bschedule\b",
    r"\bcalendar\b",
    r"\binvite\b",
    r"\b\d{1,2}\s?(am|pm)\b",
    r"\b\d{1,2}:\d{2}\b",
    r"\b(monday|tuesday|wednesday|thursday|friday|tomorrow|next week)\b",
    r"\bo'?clock\b",
]

_CONFIRM_RE = re.compile("|".join(_CONFIRM_PATTERNS), re.IGNORECASE)
_CONTEXT_RE = re.compile("|".join(_SCHEDULING_CONTEXT_PATTERNS), re.IGNORECASE)


def detect_status(
    *,
    current: str,
    user_text: str,
    agent_text: str,
) -> str:
    """Return the (possibly-updated) meeting status for the latest turn.

    ``current`` is the prior status; this never *downgrades* a ``booked``
    status. Promotion to ``booked`` requires the lead to confirm AND a
    scheduling context to be present in either the lead's words or the
    agent's proposal.
    """

    if current == MEETING_STATUS_BOOKED:
        return MEETING_STATUS_BOOKED

    user_text = user_text or ""
    agent_text = agent_text or ""

    confirmed = bool(_CONFIRM_RE.search(user_text))
    has_context = bool(_CONTEXT_RE.search(user_text)) or bool(
        _CONTEXT_RE.search(agent_text)
    )

    if confirmed and has_context:
        return MEETING_STATUS_BOOKED

    # Conversation is live but no agreement yet.
    return MEETING_STATUS_NOT_BOOKED
