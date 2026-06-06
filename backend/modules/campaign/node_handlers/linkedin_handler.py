"""LINKEDIN node handler.

Executes a LinkedIn action (connection request or direct message) against
the lead associated with the current execution.  Template rendering,
provider dispatch, and activity logging are all delegated to
:class:`~modules.campaign.linkedin_service.LinkedInService`.

Phase 2H ships a **mock provider** — the handler interface and output
shape are production-ready so swapping in a real provider (PhantomBuster,
Dux-Soup, LinkedIn API) requires only changes to
:class:`~modules.campaign.linkedin_service.LinkedInService._call_provider`.

Node config schema
------------------
::

    {
        "id":      "linkedin_1",
        "type":    "LINKEDIN",
        "action":  "CONNECT",
        "message": "Hi {{firstName}}, I'd like to connect."
    }

    {
        "id":      "linkedin_2",
        "type":    "LINKEDIN",
        "action":  "MESSAGE",
        "message": "Hi {{firstName}}, following up from {{company}}..."
    }

Supported ``action`` values: ``"CONNECT"``, ``"MESSAGE"`` (case-insensitive).

Template variables
------------------
Inherits the full set from
:class:`~modules.campaign.email_service.EmailService`:
``{{firstName}}``, ``{{lastName}}``, ``{{company}}``, ``{{jobTitle}}``,
``{{email}}``.

Execution outcomes
------------------
``advance=True`` in all cases — a LinkedIn failure is non-blocking so the
lead continues through the graph.  The exact outcome is recorded in
``node_outputs``:

* Action dispatched (mock or real):
  ``{"action": "connect", "success": true, "mock": true, ...}``
* No LinkedIn URL on lead:
  ``{"success": false, "skipped": true, "reason": "..."}``
* Unknown ``action``:
  ``{"success": false, "error": "..."}``
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from common.logging import get_logger
from modules.campaign.node_handlers.base import BaseNodeHandler, NodeResult
from modules.campaign.linkedin_service import ACTION_CONNECT, ACTION_MESSAGE

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from modules.campaign.execution_model import Execution

log = get_logger("campaign.node_handlers.linkedin")


class LinkedInNodeHandler(BaseNodeHandler):
    """Execute a LinkedIn CONNECT or MESSAGE action for the current lead."""

    async def execute(
        self,
        db: "Session",
        execution: "Execution",
        node: dict,
    ) -> NodeResult:
        from modules.campaign.linkedin_service import LinkedInService

        node_id: str = node.get("id", "")
        action: str = (node.get("action") or "").strip().upper()
        message_template: str = (node.get("message") or "").strip()

        ctx = execution.context or {}
        lead: dict = ctx.get("lead") or {}
        profile_url: str = (lead.get("linkedin_url") or "").strip()

        # ------------------------------------------------------------------ #
        # Graceful skip: no LinkedIn URL for this lead.
        # ------------------------------------------------------------------ #
        if not profile_url:
            log.info(
                "campaign.node.linkedin.no_url",
                execution_id=str(execution.id),
                node_id=node_id,
                action=action,
            )
            return NodeResult(
                outcome="skipped",
                advance=True,
                output={
                    "success": False,
                    "skipped": True,
                    "reason": "no LinkedIn URL for lead",
                },
            )

        # ------------------------------------------------------------------ #
        # Validate action
        # ------------------------------------------------------------------ #
        if action not in (ACTION_CONNECT, ACTION_MESSAGE):
            reason = (
                f"unknown LinkedIn action '{action}'; "
                f"supported: CONNECT, MESSAGE"
            )
            log.warning(
                "campaign.node.linkedin.bad_action",
                execution_id=str(execution.id),
                node_id=node_id,
                action=action,
            )
            return NodeResult(
                outcome="failed",
                advance=True,
                output={"success": False, "error": reason},
            )

        # ------------------------------------------------------------------ #
        # Resolve org_id for activity logging.
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
            pass

        lead_id: uuid.UUID | None = None
        if lead.get("id"):
            try:
                lead_id = uuid.UUID(str(lead["id"]))
            except ValueError:
                pass

        # ------------------------------------------------------------------ #
        # Dispatch (delegates to LinkedInService; never raises).
        # ------------------------------------------------------------------ #
        try:
            if action == ACTION_CONNECT:
                result = LinkedInService.send_connection_request(
                    db,
                    profile_url=profile_url,
                    message=message_template,
                    lead=lead,
                    lead_id=lead_id,
                    org_id=org_id,
                )
            else:
                result = LinkedInService.send_message(
                    db,
                    profile_url=profile_url,
                    message=message_template,
                    lead=lead,
                    lead_id=lead_id,
                    org_id=org_id,
                )
        except Exception as exc:
            log.warning(
                "campaign.node.linkedin.dispatch_error",
                execution_id=str(execution.id),
                node_id=node_id,
                action=action,
                error=str(exc),
            )
            result = {
                "action": action.lower(),
                "profile_url": profile_url,
                "success": False,
                "error": str(exc),
            }

        if result.get("success"):
            log.info(
                "campaign.node.linkedin.dispatched",
                execution_id=str(execution.id),
                node_id=node_id,
                action=action,
                profile_url=profile_url,
                mock=result.get("mock", False),
            )
        else:
            log.warning(
                "campaign.node.linkedin.failed",
                execution_id=str(execution.id),
                node_id=node_id,
                action=action,
                error=result.get("error"),
            )

        return NodeResult(
            outcome="completed" if result.get("success") else "failed",
            advance=True,
            output=result,
        )
