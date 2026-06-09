"""Email reply detection service.

Checks whether a lead has replied to a specific outbound email by searching
the sender's IMAP inbox for messages that reference the original Message-ID.

Architecture
------------
Each execution (one per lead) stores the sent email's ``message_id`` and
``sent_at`` timestamp in ``node_outputs``.  When the CONDITION node evaluates
``EMAIL_REPLIED``, it calls :func:`check_for_reply` with that data so each
lead is checked independently.

Detection strategy (in priority order)
---------------------------------------
1. **Header match** — ``SEARCH HEADER In-Reply-To <message-id>``
   Most reliable: RFC 2822 compliant clients set this header when replying.

2. **References match** — ``SEARCH HEADER References <message-id>``
   Catches threaded clients that chain message IDs in ``References``.

3. **FROM + SINCE fallback** — search all messages FROM the lead's address
   that arrived after ``sent_at`` and check for "Re:" subject prefix.
   Used when the message-id is not available or the client strips headers.

Logging
-------
Every step is logged at ``INFO`` level so operators can trace exactly what
happened for each lead's reply check:

* ``email_reply.imap_search_by_header``  — header-based IMAP search result
* ``email_reply.imap_search_fallback``   — fallback FROM-based search result
* ``email_reply.reply_found``            — reply detected with timestamp
* ``email_reply.no_reply``               — no reply found
* ``email_reply.imap_error``             — IMAP connection / search error
* ``email_reply.imap_not_configured``    — IMAP credentials not set
"""

from __future__ import annotations

import email as email_lib
import imaplib
import re
from datetime import datetime, timezone
from typing import Optional

from common.logging import get_logger

log = get_logger("campaign.email_reply_service")

_IMAP_DATE_FMT = "%d-%b-%Y"

# ---------------------------------------------------------------------------
# Negative-reply phrase list
# Any of these (case-insensitive substring match) in the reply body causes
# the email to be classified as a negative/opt-out reply.
# ---------------------------------------------------------------------------
_NEGATIVE_PHRASES: list[str] = [
    "not interested",
    "no thank",
    "please stop",
    "remove me",
    "unsubscribe",
    "do not contact",
    "don't contact",
    "dont contact",
    "opt out",
    "opt-out",
    "take me off",
    "stop emailing",
    "stop contacting",
    "leave me alone",
    "don't email",
    "do not email",
    "not for us",
    "not a fit",
    "wrong person",
    "not the right time",
    "go away",
    "never contact",
    "no interest",
]


def _is_negative_reply(body: str) -> bool:
    """Return True when *body* contains any opt-out / negative phrase."""
    lower = body.lower()
    return any(phrase in lower for phrase in _NEGATIVE_PHRASES)


def _is_configured() -> bool:
    from config.settings import settings
    return bool(settings.IMAP_HOST and settings.IMAP_USER and settings.IMAP_PASSWORD)


def check_for_reply(
    *,
    to_address: str,
    sent_at: datetime,
    window_minutes: int = 5,
    message_id: Optional[str] = None,
    execution_id: str = "",
    lead_id: str = "",
) -> dict:
    """Check whether *to_address* replied to the email sent at *sent_at*.

    Parameters
    ----------
    to_address:
        The lead's email address — the one we sent the email TO and expect
        a reply FROM.
    sent_at:
        When the email was sent (UTC).  Used as a lower-bound filter and
        to calculate whether the reply is within *window_minutes*.
    window_minutes:
        How many minutes after *sent_at* a reply still counts as "on time".
    message_id:
        The ``Message-ID`` header value of the sent email.  When supplied,
        IMAP searches for messages whose ``In-Reply-To`` or ``References``
        headers contain this value — the most accurate match strategy.
    execution_id:
        Execution UUID string for log correlation.
    lead_id:
        Lead identifier for log correlation.

    Returns
    -------
    dict
        ``replied``        – bool, True if any qualifying reply was found
        ``within_window``  – bool, True if reply arrived within *window_minutes*
        ``negative_reply`` – bool, True if reply body contains opt-out phrases
        ``replied_at``     – ISO 8601 str or None
        ``match_method``   – "header" | "fallback" | None
        ``reply_subject``  – str or None, subject of the detected reply
        ``reply_body``     – str or None, plain-text body (first 500 chars)
        ``error``          – str or None
    """
    ctx = {"execution_id": execution_id, "lead_id": lead_id, "to": to_address}

    if not _is_configured():
        log.warning("email_reply.imap_not_configured", **ctx)
        return {
            "replied": False, "within_window": False, "negative_reply": False,
            "replied_at": None, "match_method": None,
            "reply_subject": None, "reply_body": None,
            "error": "IMAP not configured — set IMAP_HOST/IMAP_USER/IMAP_PASSWORD",
        }

    try:
        return _imap_check(
            to_address=to_address,
            sent_at=sent_at,
            window_minutes=window_minutes,
            message_id=message_id,
            ctx=ctx,
        )
    except Exception as exc:
        log.error("email_reply.imap_error", error=str(exc), **ctx)
        return {
            "replied": False, "within_window": False, "negative_reply": False,
            "replied_at": None, "match_method": None,
            "reply_subject": None, "reply_body": None,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_text_body(msg: email_lib.message.Message) -> str:
    """Return the plain-text portion of an email message (up to 500 chars)."""
    body_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
    else:
        if msg.get_content_type() == "text/plain":
            charset = msg.get_content_charset() or "utf-8"
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    body_parts.append(payload.decode(charset, errors="replace"))
            except Exception:
                pass
    return " ".join(body_parts)[:500]


# ---------------------------------------------------------------------------
# Internal IMAP logic
# ---------------------------------------------------------------------------

def _connect() -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
    from config.settings import settings
    if settings.IMAP_USE_SSL:
        return imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
    return imaplib.IMAP4(settings.IMAP_HOST, settings.IMAP_PORT)


def _imap_check(
    *,
    to_address: str,
    sent_at: datetime,
    window_minutes: int,
    message_id: Optional[str],
    ctx: dict,
) -> dict:
    from config.settings import settings

    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)

    window_end_ts = sent_at.timestamp() + (window_minutes * 60)
    since_str = sent_at.strftime(_IMAP_DATE_FMT)

    conn = _connect()
    try:
        conn.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
        conn.select("INBOX", readonly=True)

        # ── Strategy 1: Header-based match (most accurate, per-lead) ─────────
        candidate_nums: list[bytes] = []
        match_method: Optional[str] = None

        if message_id:
            # Strip angle brackets for searching
            clean_mid = message_id.strip().strip("<>")

            # Search In-Reply-To
            _, data = conn.search(None, f'(HEADER "In-Reply-To" "{clean_mid}")')
            nums = data[0].split() if data[0] else []

            log.info(
                "email_reply.imap_search_by_header",
                header="In-Reply-To",
                message_id=clean_mid,
                matches=len(nums),
                **ctx,
            )

            if not nums:
                # Search References
                _, data = conn.search(None, f'(HEADER "References" "{clean_mid}")')
                nums = data[0].split() if data[0] else []
                log.info(
                    "email_reply.imap_search_by_header",
                    header="References",
                    message_id=clean_mid,
                    matches=len(nums),
                    **ctx,
                )

            if nums:
                candidate_nums = nums
                match_method = "header"

        # ── Strategy 2: FROM + SINCE fallback (less precise) ─────────────────
        if not candidate_nums:
            _, data = conn.search(
                None, f'(FROM "{to_address}" SINCE "{since_str}")'
            )
            nums = data[0].split() if data[0] else []
            log.info(
                "email_reply.imap_search_fallback",
                strategy="FROM+SINCE",
                from_addr=to_address,
                since=since_str,
                matches=len(nums),
                **ctx,
            )
            candidate_nums = nums
            if nums:
                match_method = "fallback"

        if not candidate_nums:
            log.info("email_reply.no_reply", reason="no_candidates", **ctx)
            return {
                "replied": False, "within_window": False, "negative_reply": False,
                "replied_at": None, "match_method": None,
                "reply_subject": None, "reply_body": None, "error": None,
            }

        # ── Parse candidate messages (full body for sentiment analysis) ───────
        earliest_reply: Optional[datetime] = None
        best_msg: Optional[email_lib.message.Message] = None

        for num in candidate_nums:
            _, msg_data = conn.fetch(num, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue

            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
            if not raw:
                continue

            msg = email_lib.message_from_bytes(raw)

            # Parse the Date header
            date_str = msg.get("Date", "")
            try:
                from email.utils import parsedate_to_datetime
                msg_dt = parsedate_to_datetime(date_str)
                if msg_dt.tzinfo is None:
                    msg_dt = msg_dt.replace(tzinfo=timezone.utc)
            except Exception:
                log.debug(
                    "email_reply.date_parse_failed",
                    date_str=date_str, msg_num=num, **ctx,
                )
                continue

            # Must have arrived after the email was sent
            if msg_dt <= sent_at:
                log.debug(
                    "email_reply.candidate_too_old",
                    msg_dt=msg_dt.isoformat(), sent_at=sent_at.isoformat(), **ctx,
                )
                continue

            # For fallback strategy: also require "Re:" subject prefix
            if match_method == "fallback":
                subj = msg.get("Subject", "")
                if not re.match(r"re:", subj, re.IGNORECASE):
                    log.debug(
                        "email_reply.fallback_no_re_subject",
                        subject=subj, **ctx,
                    )
                    continue

            if earliest_reply is None or msg_dt < earliest_reply:
                earliest_reply = msg_dt
                best_msg = msg
                log.debug(
                    "email_reply.candidate_accepted",
                    msg_dt=msg_dt.isoformat(),
                    subject=msg.get("Subject", ""),
                    match_method=match_method,
                    **ctx,
                )

        if earliest_reply is None or best_msg is None:
            log.info(
                "email_reply.no_reply",
                reason="no_valid_candidates_after_filtering",
                candidates_checked=len(candidate_nums),
                **ctx,
            )
            return {
                "replied": False, "within_window": False, "negative_reply": False,
                "replied_at": None, "match_method": match_method,
                "reply_subject": None, "reply_body": None, "error": None,
            }

        within = earliest_reply.timestamp() <= window_end_ts

        # ── Extract plain-text body for negative-reply sentiment ─────────────
        reply_subject = best_msg.get("Subject", "")
        reply_body = _extract_text_body(best_msg)
        is_negative = _is_negative_reply(reply_subject + " " + reply_body)

        log.info(
            "email_reply.reply_found",
            replied_at=earliest_reply.isoformat(),
            within_window=within,
            negative_reply=is_negative,
            match_method=match_method,
            window_minutes=window_minutes,
            subject=reply_subject,
            body_preview=reply_body[:120],
            **ctx,
        )

        return {
            "replied": True,
            "within_window": within,
            "negative_reply": is_negative,
            "replied_at": earliest_reply.isoformat(),
            "match_method": match_method,
            "reply_subject": reply_subject,
            "reply_body": reply_body[:500],
            "error": None,
        }

    finally:
        try:
            conn.logout()
        except Exception:
            pass
