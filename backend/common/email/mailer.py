"""SMTP-based email sender.

Uses stdlib smtplib so no extra dependency is required. Sending happens on a
background thread so request handlers never block on the network. SMTP errors
are logged but never raised to the caller — failing to deliver an invitation
must not break member creation.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr
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
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_USER))
    msg["To"] = to
    msg["Subject"] = subject
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
) -> None:
    """Send synchronously. Raises on failure. Prefer `send_email_async`."""
    if not _smtp_configured():
        raise RuntimeError("SMTP is not configured")
    msg = _build_message(
        to=to, subject=subject, text_body=text_body, html_body=html_body
    )
    _send_sync(msg)


def send_email_async(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> None:
    """Fire-and-forget. Errors are logged, never raised."""
    if not _smtp_configured():
        logger.warning(
            "SMTP not configured; skipping email to %s (subject=%r)", to, subject
        )
        return

    msg = _build_message(
        to=to, subject=subject, text_body=text_body, html_body=html_body
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
