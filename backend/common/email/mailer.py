"""SMTP-based email sender.

Uses stdlib smtplib so no extra dependency is required. Sending happens on a
background thread so request handlers never block on the network. SMTP errors
are logged but never raised to the caller — failing to deliver an invitation
must not break member creation.

Thread continuity
-----------------
``send_email`` and ``send_email_async`` accept optional ``in_reply_to`` and
``references`` parameters. When set they are added as RFC 2822 headers so
Gmail, Outlook, and Apple Mail all group replies in the same thread:

* ``In-Reply-To`` — the ``Message-ID`` of the immediately preceding message.
* ``References`` — space-separated chain of all ancestor ``Message-ID`` values.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Iterable

from config.settings import settings

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    return bool(
        settings.SMTP_HOST
        and settings.SMTP_USER
        and settings.SMTP_PASSWORD
    )


def _build_message(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    # Generate a globally unique Message-ID so replies can be correlated via
    # In-Reply-To / References headers when the inbound webhook fires.
    domain = (
        settings.SMTP_USER.split("@")[1]
        if "@" in settings.SMTP_USER
        else "aifficient.co"
    )
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_USER))
    msg["To"] = to
    msg["Subject"] = subject

    # Threading headers — set when this is a reply in an ongoing conversation.
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    return msg


def _send_sync(message: EmailMessage) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(message)


def send_email(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> dict:
    """Send synchronously. Raises on failure. Prefer `send_email_async`.

    Returns a dict with ``message_id`` so callers can track the sent email.
    Pass ``in_reply_to`` and ``references`` when sending a reply in an existing
    thread to maintain Gmail/Outlook thread grouping.
    """
    if not _smtp_configured():
        raise RuntimeError("SMTP is not configured")
    msg = _build_message(
        to=to,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        in_reply_to=in_reply_to,
        references=references,
    )
    _send_sync(msg)
    return {"message_id": msg["Message-ID"]}


def send_email_async(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> None:
    """Fire-and-forget. Errors are logged, never raised."""
    if not _smtp_configured():
        logger.warning(
            "SMTP not configured; skipping email to %s (subject=%r)", to, subject
        )
        return

    msg = _build_message(
        to=to,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        in_reply_to=in_reply_to,
        references=references,
    )

    def _worker() -> None:
        try:
            _send_sync(msg)
            logger.info("Sent email to %s (subject=%r)", to, subject)
        except Exception:
            logger.exception("Failed to send email to %s", to)

    threading.Thread(target=_worker, daemon=True).start()


def to_recipient_list(emails: Iterable[str]) -> str:
    return ", ".join(e for e in emails if e)
