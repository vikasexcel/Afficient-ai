"""Campaign LinkedIn service.

``LinkedInService`` is the abstraction layer for all campaign-originated
LinkedIn actions.  Phase 2H ships a **mock provider** that returns
structured responses without performing any browser automation — the full
provider integration (PhantomBuster, Dux-Soup, or a direct LinkedIn API
wrapper) can be wired in here without touching the handler or the graph.

Responsibilities
----------------
* **Template rendering** — delegates to
  :func:`~modules.campaign.email_service.EmailService.render_template` so
  the same ``{{firstName}}``, ``{{lastName}}``, ``{{company}}``,
  ``{{jobTitle}}``, ``{{email}}`` placeholders work identically for
  LinkedIn messages.
* **Template validation** — surface unknown tokens before a workflow runs.
* **Connection requests** — ``send_connection_request`` renders the
  invitation note and dispatches it (mock in Phase 2H).
* **Direct messages** — ``send_message`` renders the body and dispatches
  it (mock in Phase 2H).
* **Activity logging** — every attempt writes a
  :class:`~modules.leads.model.LeadActivity` row (``li_connect``,
  ``li_message``, or ``li_failed``) for the lead timeline.

Provider contract
-----------------
All send methods return a plain dict with at minimum:

==============================  ==============================================
Key                             Description
==============================  ==============================================
``action``                      ``"connect"`` or ``"message"``
``profile_url``                 LinkedIn profile URL targeted
``message``                     Rendered message text (or empty string)
``provider``                    ``"mock"`` (Phase 2H) / future real provider
``success``                     ``True`` when action was accepted
``mock``                        ``True`` while using the mock provider
``error``                       Present only on failure (``str``)
==============================  ==============================================

Swapping the mock for a real provider requires only implementing the same
dict return shape in :meth:`~LinkedInService._call_provider` and toggling
the provider name in settings.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from common.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = get_logger("campaign.linkedin_service")

# Supported actions (upper-case, mirrors node config ``action`` field).
ACTION_CONNECT = "CONNECT"
ACTION_MESSAGE = "MESSAGE"
SUPPORTED_ACTIONS = frozenset({ACTION_CONNECT, ACTION_MESSAGE})


class LinkedInService:

    # ------------------------------------------------------------------ #
    # Template helpers (delegates to EmailService — same token set)
    # ------------------------------------------------------------------ #

    @staticmethod
    def render_template(template: str, lead: dict) -> str:
        """Render ``{{token}}`` placeholders from lead context data.

        Delegates to :meth:`~modules.campaign.email_service.EmailService.
        render_template` so LinkedIn messages support the same tokens as
        email: ``{{firstName}}``, ``{{lastName}}``, ``{{company}}``,
        ``{{jobTitle}}``, ``{{email}}``.
        """
        from modules.campaign.email_service import EmailService

        return EmailService.render_template(template, lead)

    @staticmethod
    def validate_template(template: str) -> list[str]:
        """Return validation errors for ``{{token}}`` usage in *template*.

        Delegates to :meth:`~modules.campaign.email_service.EmailService.
        validate_template`.  An empty list means the template is valid.
        """
        from modules.campaign.email_service import EmailService

        return EmailService.validate_template(template, template)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    @staticmethod
    def send_connection_request(
        db: "Session",
        *,
        profile_url: str,
        message: str,
        lead: dict,
        lead_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
    ) -> dict:
        """Send (or mock) a LinkedIn connection request with an invite note.

        Parameters
        ----------
        db:
            Active SQLAlchemy session — used only for activity logging.
        profile_url:
            LinkedIn profile URL of the target.
        message:
            Invitation note template (``{{firstName}}`` etc. are rendered).
        lead:
            Lead context dict from the execution.
        lead_id / org_id:
            Used for activity logging; either may be ``None`` to skip logging.

        Returns
        -------
        dict
            Provider response with ``action``, ``profile_url``, ``message``,
            ``provider``, ``success``, ``mock``.
        """
        rendered = LinkedInService.render_template(message, lead)
        result = LinkedInService._call_provider(
            action=ACTION_CONNECT,
            profile_url=profile_url,
            rendered_message=rendered,
        )
        LinkedInService._log_activity(
            db,
            lead_id=lead_id,
            org_id=org_id,
            action=ACTION_CONNECT,
            success=result["success"],
            profile_url=profile_url,
            message=rendered,
            error=result.get("error"),
        )
        return result

    @staticmethod
    def send_message(
        db: "Session",
        *,
        profile_url: str,
        message: str,
        lead: dict,
        lead_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
    ) -> dict:
        """Send (or mock) a LinkedIn direct message.

        Same contract as :meth:`send_connection_request`.
        """
        rendered = LinkedInService.render_template(message, lead)
        result = LinkedInService._call_provider(
            action=ACTION_MESSAGE,
            profile_url=profile_url,
            rendered_message=rendered,
        )
        LinkedInService._log_activity(
            db,
            lead_id=lead_id,
            org_id=org_id,
            action=ACTION_MESSAGE,
            success=result["success"],
            profile_url=profile_url,
            message=rendered,
            error=result.get("error"),
        )
        return result

    # ------------------------------------------------------------------ #
    # Provider layer (mock in Phase 2H)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _call_provider(
        *,
        action: str,
        profile_url: str,
        rendered_message: str,
    ) -> dict:
        """Dispatch to the configured LinkedIn provider.

        Phase 2H returns a mock success response.  Replace this method (or
        branch on a ``LINKEDIN_PROVIDER`` setting) to integrate a real
        automation provider without changing the public API.
        """
        log.info(
            "campaign.linkedin.mock_dispatch",
            action=action.lower(),
            profile_url=profile_url,
        )
        return {
            "action": action.lower(),
            "profile_url": profile_url,
            "message": rendered_message,
            "provider": "mock",
            "success": True,
            "mock": True,
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
        action: str,
        success: bool,
        profile_url: str,
        message: str,
        error: str | None,
    ) -> None:
        """Write a :class:`~modules.leads.model.LeadActivity` row.

        Skipped gracefully when ``lead_id`` or ``org_id`` is absent.
        """
        if lead_id is None or org_id is None:
            return

        from modules.leads.model import (
            ACTIVITY_LI_CONNECT,
            ACTIVITY_LI_FAILED,
            ACTIVITY_LI_MESSAGE,
            LeadActivity,
        )

        if not success:
            activity_type = ACTIVITY_LI_FAILED
        elif action == ACTION_CONNECT:
            activity_type = ACTIVITY_LI_CONNECT
        else:
            activity_type = ACTIVITY_LI_MESSAGE

        notes_parts = [
            f"action={action.lower()}",
            f"profile={profile_url}",
            f"message={message!r}"[:200],
        ]
        if error:
            notes_parts.append(f"error={error}")
        notes = "; ".join(notes_parts)[:2000]

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
                "campaign.linkedin.activity_log_failed",
                lead_id=str(lead_id),
                error=str(exc),
            )
            db.rollback()
