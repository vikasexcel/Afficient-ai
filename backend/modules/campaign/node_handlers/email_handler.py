"""EMAIL node handler.

Sends a personalised outbound email to the lead associated with the current
execution.  Template rendering, SMTP dispatch, and activity logging are all
delegated to :class:`~modules.campaign.email_service.EmailService`.

Node config schema
------------------
::

    {
        "id":       "email_1",
        "type":     "EMAIL",
        "subject":  "Hi {{firstName}}, quick note about {{company}}",
        "body":     "Hi {{firstName}},\\n\\nI wanted to reach out...",
        "provider": "smtp"
    }

``provider`` is informational only in Phase 2F (only ``smtp`` is supported).
Future phases may add ``sendgrid``, ``ses``, etc. without changing this
handler's interface.

Execution outcomes
------------------
``advance=True`` in all cases — an email failure is non-blocking so the
lead continues through the rest of the graph.  The exact outcome is surfaced
in ``node_outputs``:

* Email sent:     ``{"sent": true, "to": "...", "subject": "..."}``
* SMTP unconfigured / send error:
                  ``{"sent": false, "to": "...", "error": "..."}``
* No email address on lead:
                  ``{"sent": false, "skipped": true, "reason": "..."}``
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from common.logging import get_logger
from modules.campaign.node_handlers.base import BaseNodeHandler, NodeResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from modules.campaign.execution_model import Execution

log = get_logger("campaign.node_handlers.email")


class EmailNodeHandler(BaseNodeHandler):
    """Send a templated email to the lead and advance the graph."""

    async def execute(
        self,
        db: "Session",
        execution: "Execution",
        node: dict,
    ) -> NodeResult:
        from modules.campaign.email_service import EmailService

        node_id: str = node.get("id", "")
        ctx = execution.context or {}
        lead: dict = ctx.get("lead") or {}
        to_email: str = (lead.get("email") or "").strip()

        # ------------------------------------------------------------------ #
        # Graceful skip: no email address for this lead.
        # ------------------------------------------------------------------ #
        if not to_email:
            log.info(
                "campaign.node.email.no_address",
                execution_id=str(execution.id),
                node_id=node_id,
            )
            return NodeResult(
                outcome="skipped",
                advance=True,
                output={
                    "sent": False,
                    "skipped": True,
                    "reason": "no email address for lead",
                },
            )

        subject_template: str = node.get("subject") or ""
        body_template: str = node.get("body") or ""

        # ------------------------------------------------------------------ #
        # Resolve org_id from the campaign context so the activity can be
        # tenant-scoped.  Falls back to None when the context was created by
        # an older code path that did not include campaign_id.
        # ------------------------------------------------------------------ #
        org_id: uuid.UUID | None = None
        try:
            from modules.campaign.model import Campaign
            from modules.campaign.workflow_model import Workflow

            workflow = db.get(Workflow, execution.workflow_id)
            if workflow is not None:
                campaign = db.get(Campaign, workflow.campaign_id)
                if campaign is not None:
                    org_id = campaign.organization_id
        except Exception:
            pass  # Non-critical — activity is simply not org-scoped.

        lead_id: uuid.UUID | None = None
        if lead.get("id"):
            try:
                lead_id = uuid.UUID(str(lead["id"]))
            except ValueError:
                pass

        # ------------------------------------------------------------------ #
        # Send (delegated to EmailService; never raises).
        # ------------------------------------------------------------------ #
        result = EmailService.send_email(
            db,
            to=to_email,
            subject_template=subject_template,
            body_template=body_template,
            lead=lead,
            lead_id=lead_id,
            org_id=org_id,
        )

        if result["sent"]:
            log.info(
                "campaign.node.email.sent",
                execution_id=str(execution.id),
                node_id=node_id,
                to=to_email,
                subject=result.get("subject"),
            )
        else:
            log.warning(
                "campaign.node.email.failed",
                execution_id=str(execution.id),
                node_id=node_id,
                to=to_email,
                error=result.get("error"),
            )

        return NodeResult(
            outcome="completed" if result["sent"] else "failed",
            advance=True,
            output=result,
        )
