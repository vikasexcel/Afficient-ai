"""Campaign email service.

``EmailService`` is the single entry-point for all campaign-originated
outbound emails.  It owns:

* **Template rendering** — ``{{placeholder}}`` substitution from lead context
  data with safe fallbacks for any missing fields.
* **Template validation** — detect unknown or empty placeholders before a
  workflow is activated.
* **Sending** — delegates to :mod:`common.email.mailer` (stdlib ``smtplib``),
  which requires ``SMTP_HOST / SMTP_USER / SMTP_PASSWORD`` to be configured.
  When SMTP is not configured the send is skipped and the result is marked
  ``sent=False`` rather than raising so the graph can still advance.
* **Activity logging** — writes a :class:`~modules.leads.model.LeadActivity`
  row (``email_sent`` or ``email_failed``) for every attempt so the lead
  timeline stays accurate.

Template variables
------------------
All variables use double-brace syntax and are case-sensitive:

==============================  ==============================
Token                           Source
==============================  ==============================
``{{firstName}}``               ``lead.first_name``
``{{lastName}}``                ``lead.last_name``
``{{company}}``                 ``lead.company``
``{{jobTitle}}``                ``lead.job_title``
``{{email}}``                   ``lead.email``
``{{phone}}``                   ``lead.phone``
``{{name}}``                    ``lead.name`` (full name)
==============================  ==============================

Older execution contexts that pre-date the Phase 2F lead-context expansion
may lack ``first_name`` / ``last_name`` / ``job_title``.  The renderer
falls back to splitting the ``name`` field so those executions still work.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from common.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = get_logger("campaign.email_service")

# ---------------------------------------------------------------------------
# Template vocabulary
# ---------------------------------------------------------------------------

#: All recognised ``{{token}}`` names, mapped to the key they resolve from the
#: lead context dict.  Order here controls validation error messages.
_TOKEN_MAP: dict[str, str] = {
    "firstName": "first_name",
    "lastName": "last_name",
    "company": "company",
    "jobTitle": "job_title",
    "email": "email",
    "phone": "phone",
    "name": "name",
}

_KNOWN_TOKENS: frozenset[str] = frozenset(_TOKEN_MAP)
_TOKEN_RE = re.compile(r"\{\{(\w+)\}\}")


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


class EmailService:

    # ------------------------------------------------------------------ #
    # Template rendering
    # ------------------------------------------------------------------ #

    @staticmethod
    def render_template(template: str, lead: dict) -> str:
        """Replace every ``{{token}}`` in *template* with lead data.

        Unknown tokens are left as-is so callers can detect them via
        :meth:`validate_template` before rendering.  Missing lead fields
        render as empty string so recipients never see a raw ``{{token}}``.
        """
        # Derive first/last from full name when not explicitly stored (legacy
        # execution contexts created before Phase 2F).
        name = lead.get("name", "")
        name_parts = name.split(None, 1)
        first = lead.get("first_name") or (name_parts[0] if name_parts else "")
        last = lead.get("last_name") or (name_parts[1] if len(name_parts) > 1 else "")

        values: dict[str, str] = {
            "firstName": first,
            "lastName": last,
            "company": lead.get("company") or "",
            "jobTitle": lead.get("job_title") or "",
            "email": lead.get("email") or "",
            "phone": lead.get("phone") or "",
            "name": name,
        }

        def _replace(match: re.Match) -> str:
            token = match.group(1)
            return values.get(token, match.group(0))  # unknown → leave unchanged

        return _TOKEN_RE.sub(_replace, template)

    @staticmethod
    def validate_template(subject: str, body: str) -> list[str]:
        """Return a list of validation error messages.

        An empty list means the templates are valid and ready to use.
        Currently checks for:
        * Unrecognised ``{{token}}`` names in subject or body.
        """
        errors: list[str] = []
        for field_name, text in (("subject", subject), ("body", body)):
            for match in _TOKEN_RE.finditer(text):
                token = match.group(1)
                if token not in _KNOWN_TOKENS:
                    errors.append(
                        f"{field_name}: unknown template token '{{{{ {token} }}}}'"
                    )
        return errors

    # ------------------------------------------------------------------ #
    # Sending
    # ------------------------------------------------------------------ #

    @staticmethod
    def send_email(
        db: "Session",
        *,
        to: str,
        subject_template: str,
        body_template: str,
        lead: dict,
        lead_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
    ) -> dict:
        """Render templates, send the email, and log the outcome.

        Returns a result dict with keys:
        ``to``, ``subject``, ``sent`` (bool), ``error`` (str | None).

        Never raises — failures are captured in the returned dict so the
        graph executor can record them in ``node_outputs`` and decide
        whether to continue.
        """
        from common.email.mailer import send_email as _smtp_send

        subject = EmailService.render_template(subject_template, lead)
        body = EmailService.render_template(body_template, lead)

        error: str | None = None
        sent = False
        message_id: str | None = None
        sent_at: str | None = None

        try:
            result_meta = _smtp_send(to=to, subject=subject, text_body=body)
            sent = True
            sent_at = datetime.now(timezone.utc).isoformat()
            # _smtp_send now returns {"message_id": "<...>"} — capture it so the
            # CONDITION/EMAIL_REPLIED handler can search IMAP by In-Reply-To header.
            if isinstance(result_meta, dict):
                message_id = result_meta.get("message_id")
            log.info(
                "campaign.email.sent_with_tracking",
                to=to,
                subject=subject,
                message_id=message_id,
                sent_at=sent_at,
            )
        except Exception as exc:
            error = str(exc)
            log.warning(
                "campaign.email.send_failed",
                to=to,
                error=error,
            )

        EmailService._log_activity(
            db,
            lead_id=lead_id,
            org_id=org_id,
            sent=sent,
            to=to,
            subject=subject,
            error=error,
        )

        return {
            "to": to,
            "subject": subject,
            "sent": sent,
            "sent_at": sent_at,
            "message_id": message_id,
            "error": error,
        }

    # ------------------------------------------------------------------ #
    # Activity logging
    # ------------------------------------------------------------------ #

    @staticmethod
    def _log_activity(
        db: "Session",
        *,
        lead_id: uuid.UUID | None,
        org_id: uuid.UUID | None,
        sent: bool,
        to: str,
        subject: str,
        error: str | None,
    ) -> None:
        """Write a ``LeadActivity`` row for the send attempt.

        Skipped gracefully when ``lead_id`` or ``org_id`` is absent — some
        unit-test or ad-hoc paths may not have a real lead reference.
        """
        if lead_id is None or org_id is None:
            return

        from modules.leads.model import (
            ACTIVITY_EMAIL_FAILED,
            ACTIVITY_EMAIL_SENT,
            LeadActivity,
        )

        activity_type = ACTIVITY_EMAIL_SENT if sent else ACTIVITY_EMAIL_FAILED
        notes_parts = [f"to={to}", f"subject={subject!r}"]
        if error:
            notes_parts.append(f"error={error}")
        notes = "; ".join(notes_parts)[:2000]  # guard against oversized text

        activity = LeadActivity(
            organization_id=org_id,
            lead_id=lead_id,
            user_id=None,
            activity_type=activity_type,
            notes=notes,
        )
        db.add(activity)
        try:
            db.flush()
        except Exception as exc:  # pragma: no cover — defensive
            log.warning(
                "campaign.email.activity_log_failed",
                lead_id=str(lead_id),
                error=str(exc),
            )
            db.rollback()
