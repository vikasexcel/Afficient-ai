"""Meeting confirmation email — HTML + plain text.

Sent fire-and-forget after a successful Google Calendar booking.
Uses the existing SMTP mailer (``common.email.mailer``).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from common.logging import get_logger

log = get_logger("email.meeting_confirmation")


def _format_dt(dt: Optional[datetime], tz_name: str) -> str:
    if dt is None:
        return "your scheduled time"
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
        local = dt.astimezone(tz)
        return local.strftime("%A, %B %-d at %-I:%M %p %Z")
    except Exception:
        utc = dt.astimezone(timezone.utc)
        return utc.strftime("%A, %B %-d at %-I:%M %p UTC")


def _build_html(
    to_name: str,
    slot_display: str,
    duration_minutes: int,
    meet_link: str,
    organizer_name: str,
) -> str:
    meet_section = ""
    if meet_link:
        meet_section = f"""
        <div style="margin: 24px 0; text-align: center;">
          <a href="{meet_link}"
             style="background:#1a73e8;color:#fff;padding:12px 28px;
                    border-radius:6px;text-decoration:none;font-size:15px;
                    font-weight:600;">
            Join with Google Meet
          </a>
        </div>
        <p style="text-align:center;font-size:13px;color:#666;">
          Or copy the link: <a href="{meet_link}" style="color:#1a73e8;">{meet_link}</a>
        </p>
        """

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;background:#f6f6f6;margin:0;padding:0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#fff;border-radius:8px;
                      box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="background:#1a73e8;padding:28px 40px;">
              <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">
                ✅ Meeting Confirmed
              </h1>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px 40px;">
              <p style="font-size:16px;color:#333;margin:0 0 16px;">
                Hi {to_name},
              </p>
              <p style="font-size:15px;color:#555;margin:0 0 24px;">
                Your meeting has been confirmed. Here are the details:
              </p>

              <!-- Details box -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#f8f9fa;border-radius:6px;border:1px solid #e8eaed;">
                <tr>
                  <td style="padding:20px 24px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding:6px 0;font-size:14px;color:#666;width:120px;">📅 Date &amp; Time</td>
                        <td style="padding:6px 0;font-size:14px;color:#333;font-weight:600;">{slot_display}</td>
                      </tr>
                      <tr>
                        <td style="padding:6px 0;font-size:14px;color:#666;">⏱ Duration</td>
                        <td style="padding:6px 0;font-size:14px;color:#333;">{duration_minutes} minutes</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              {meet_section}

              <p style="font-size:14px;color:#555;margin:24px 0 0;">
                A calendar invitation has been sent to your email address.
                You can add it to your calendar from there.
              </p>

              <p style="font-size:14px;color:#555;margin:16px 0 0;">
                If you need to reschedule or have any questions, please reply to
                this email.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f8f9fa;padding:20px 40px;
                       border-top:1px solid #e8eaed;">
              <p style="font-size:12px;color:#999;margin:0;text-align:center;">
                This meeting was booked by {organizer_name}. &nbsp;|&nbsp;
                Powered by Aifficient
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _build_text(
    to_name: str,
    slot_display: str,
    duration_minutes: int,
    meet_link: str,
    organizer_name: str,
) -> str:
    lines = [
        f"Hi {to_name},",
        "",
        "Your meeting has been confirmed.",
        "",
        f"Date & Time : {slot_display}",
        f"Duration    : {duration_minutes} minutes",
    ]
    if meet_link:
        lines += ["", f"Google Meet : {meet_link}"]
    lines += [
        "",
        "A calendar invitation has been sent to your email.",
        "",
        f"This meeting was booked by {organizer_name}.",
    ]
    return "\n".join(lines)


async def send_meeting_confirmation(
    *,
    to_email: str,
    to_name: str,
    slot: Optional[datetime],
    meet_link: Optional[str],
    organizer_name: str,
    timezone: str = "UTC",
    duration_minutes: int = 30,
) -> None:
    """Send the HTML confirmation email via the existing SMTP mailer."""
    if not to_email:
        log.warning("meeting_confirmation.no_email")
        return

    slot_display = _format_dt(slot, timezone)
    html = _build_html(to_name, slot_display, duration_minutes, meet_link or "", organizer_name)
    text = _build_text(to_name, slot_display, duration_minutes, meet_link or "", organizer_name)

    try:
        import asyncio as _asyncio
        from common.email.mailer import send_email

        # Use the sync send_email (raises on failure) inside to_thread so the
        # actual SMTP connection runs off the event loop without the
        # double-daemon-thread issue of send_email_async.
        await _asyncio.to_thread(
            send_email,
            to=to_email,
            subject="Meeting Confirmed — Calendar Invitation Sent",
            html_body=html,
            text_body=text,
        )
        log.info("meeting_confirmation.sent", to_email=to_email, slot=slot_display)
    except Exception as exc:
        log.warning("meeting_confirmation.send_failed", to_email=to_email, error=str(exc))
