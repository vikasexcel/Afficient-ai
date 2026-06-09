"""CONDITION node handler.

Evaluates a stored node output against a declared condition and routes
the execution to the matching branch.  This is a **zero-side-effect** node
— it reads data already in ``execution.node_outputs`` and sets
:attr:`~modules.campaign.node_handlers.base.NodeResult.next_node_id` so the
run loop advances directly to the selected branch target.

Node config schema
------------------
::

    {
        "id":             "condition_1",
        "type":           "CONDITION",
        "condition_type": "EMAIL_SENT",
        "source_node":    "email_1"
    }

For EMAIL_REPLIED conditions an extra optional ``window_minutes`` field
controls how many minutes after the email was sent are considered "on time":

::

    {
        "id":             "condition_1",
        "type":           "CONDITION",
        "condition_type": "EMAIL_REPLIED",
        "source_node":    "email_1",
        "window_minutes": 5
    }

Fields
~~~~~~
``condition_type``
    One of ``EMAIL_SENT``, ``EMAIL_FAILED``, ``EMAIL_REPLIED``,
    ``CALL_COMPLETED``, ``CALL_FAILED`` (case-insensitive).

``source_node``
    The ``id`` of the node whose output is inspected.  The handler reads
    ``execution.node_outputs[source_node]`` as the evaluation context.

``window_minutes`` *(EMAIL_REPLIED only)*
    Number of minutes after the email was sent within which a reply is
    considered timely.  Defaults to 5.

Edge schema
-----------
Each outbound edge from a CONDITION node must declare its branch label::

    {"id": "e1", "source": "condition_1", "target": "call_1",  "condition": "TRUE"}
    {"id": "e2", "source": "condition_1", "target": "stop_1",  "condition": "FALSE"}

A default (unlabelled) edge may be added as a catch-all when neither
``"TRUE"`` nor ``"FALSE"`` matches.

Execution outcomes
------------------
``advance=True`` in all success cases — :attr:`NodeResult.next_node_id`
carries the selected branch target so the run loop can jump directly to it.

``advance=False`` only on hard errors (unknown condition type, missing
source node output, no matching branch).  The execution is marked
``failed`` so operators can investigate and the retry engine responds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.logging import get_logger
from modules.campaign.node_handlers.base import BaseNodeHandler, NodeResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from modules.campaign.execution_model import Execution

log = get_logger("campaign.node_handlers.condition")


class ConditionNodeHandler(BaseNodeHandler):
    """Route the execution to a TRUE or FALSE branch."""

    async def execute(
        self,
        db: "Session",
        execution: "Execution",
        node: dict,
    ) -> NodeResult:
        from modules.campaign.workflow_model import Workflow
        from modules.campaign.workflow_service import WorkflowService

        node_id: str = node.get("id", "")
        condition_type: str = (node.get("condition_type") or "").strip().upper()
        source_node_id: str = (node.get("source_node") or "").strip()
        window_minutes: int = int(node.get("window_minutes") or 5)

        # ------------------------------------------------------------------ #
        # Validate config
        # ------------------------------------------------------------------ #
        if not condition_type:
            return self._fail(
                db, execution, node_id,
                "CONDITION node missing 'condition_type'",
            )
        if not source_node_id:
            return self._fail(
                db, execution, node_id,
                "CONDITION node missing 'source_node'",
            )

        # ------------------------------------------------------------------ #
        # Evaluate condition against stored node output
        # ------------------------------------------------------------------ #
        node_outputs: dict = execution.node_outputs or {}
        source_output: dict = dict(node_outputs.get(source_node_id) or {})

        if not node_outputs.get(source_node_id) and source_node_id:
            log.debug(
                "campaign.node.condition.source_empty",
                execution_id=str(execution.id),
                node_id=node_id,
                source_node=source_node_id,
            )
            # Treat missing output as an empty dict — evaluators handle this
            # (e.g. EMAIL_SENT → sent=False when output is absent).

        # ------------------------------------------------------------------ #
        # EMAIL_REPLIED / NEGATIVE_REPLY: check if the inbound webhook has
        # already flagged the reply.  When "replied" is already True (set by
        # the webhook path), skip the IMAP poll entirely — the reply was
        # captured in real-time and there is nothing new to search for.
        # Fall back to IMAP only when the webhook has NOT yet fired (e.g.
        # the provider is slow, or IMAP is being used without a webhook).
        # ------------------------------------------------------------------ #
        if condition_type in ("EMAIL_REPLIED", "NEGATIVE_REPLY"):
            webhook_replied = bool(source_output.get("replied"))
            lead_ctx = (execution.context or {}).get("lead") or {}
            lead_id = str(lead_ctx.get("id") or lead_ctx.get("email") or "")

            if not webhook_replied:
                # Webhook hasn't fired yet — fall back to IMAP polling.
                source_output = self._enrich_with_reply_check(
                    source_output=source_output,
                    window_minutes=window_minutes,
                    node_id=node_id,
                    execution_id=str(execution.id),
                    lead_id=lead_id,
                )
            else:
                log.info(
                    "campaign.node.condition.email_reply_check.webhook_already_set",
                    execution_id=str(execution.id),
                    node_id=node_id,
                    lead_id=lead_id,
                    match_method=source_output.get("match_method", "webhook"),
                )

            # Persist the enriched output back so future condition nodes or
            # diagnostic tools can see the reply detection result.
            node_outputs[source_node_id] = source_output
            execution.node_outputs = node_outputs

            # Emit reply_recv activity when a reply is confirmed (either path).
            if source_output.get("replied"):
                self._emit_reply_received_activity(db, execution, source_output)

        try:
            condition_result = WorkflowService.evaluate_condition(
                condition_type=condition_type,
                source_output=source_output,
            )
        except ValueError as exc:
            return self._fail(db, execution, node_id, str(exc))

        # ------------------------------------------------------------------ #
        # Resolve branch target
        # ------------------------------------------------------------------ #
        workflow = db.get(Workflow, execution.workflow_id)
        if workflow is None:
            return self._fail(
                db, execution, node_id,
                f"workflow {execution.workflow_id} not found",
            )

        target_node = WorkflowService.get_condition_target(
            workflow, node_id, condition_result=condition_result
        )
        if target_node is None:
            label = "TRUE" if condition_result else "FALSE"
            return self._fail(
                db, execution, node_id,
                f"no outbound edge labelled '{label}' from condition node "
                f"'{node_id}'",
            )

        label = "TRUE" if condition_result else "FALSE"
        log.info(
            "campaign.node.condition.branched",
            execution_id=str(execution.id),
            node_id=node_id,
            condition_type=condition_type,
            source_node=source_node_id,
            result=label,
            next_node=target_node["id"],
        )

        # Record the condition evaluation on the lead timeline so the audit
        # trail shows every branch decision (per-lead).
        self._emit_cond_eval_activity(
            db, execution,
            condition_type=condition_type,
            result_label=label,
            next_node=target_node["id"],
        )

        # ------------------------------------------------------------------ #
        # Negative reply → mark lead as lost + log activity (per-lead).
        # This runs regardless of which branch is taken so the lead record is
        # always updated when a negative reply is detected.
        # ------------------------------------------------------------------ #
        if condition_type == "NEGATIVE_REPLY" and source_output.get("negative_reply"):
            self._handle_negative_reply(db, execution, source_output)

        return NodeResult(
            outcome=label,
            advance=True,
            output={
                "condition_type": condition_type,
                "condition_result": condition_result,
                "source_node": source_node_id,
                "next_node": target_node["id"],
            },
            next_node_id=target_node["id"],
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _handle_negative_reply(
        db: "Session",
        execution: "Execution",
        source_output: dict,
    ) -> None:
        """Mark the lead as lost and write a reply_neg activity row.

        Called when the NEGATIVE_REPLY condition evaluates to True so every
        negative opt-out is permanently recorded against the lead regardless
        of what the workflow does next.
        """
        import uuid
        from modules.leads.model import (
            Lead,
            LeadActivity,
            LEAD_STATUS_LOST,
            ACTIVITY_REPLY_NEGATIVE,
        )

        ctx = execution.context or {}
        lead_ctx = ctx.get("lead") or {}
        lead_id_raw = lead_ctx.get("id")
        org_id_raw = ctx.get("org_id") or lead_ctx.get("organization_id")

        if not lead_id_raw or not org_id_raw:
            log.warning(
                "campaign.node.condition.negative_reply.missing_lead_ctx",
                execution_id=str(execution.id),
            )
            return

        try:
            lead_id = uuid.UUID(str(lead_id_raw))
            org_id = uuid.UUID(str(org_id_raw))
        except ValueError:
            return

        # Mark lead status = lost (do-not-contact)
        lead = db.get(Lead, lead_id)
        if lead and lead.status != LEAD_STATUS_LOST:
            lead.status = LEAD_STATUS_LOST
            db.flush()

        # Write activity row
        activity = LeadActivity(
            organization_id=org_id,
            lead_id=lead_id,
            activity_type=ACTIVITY_REPLY_NEGATIVE,
            notes=(
                f"Negative reply detected. "
                f"Subject: {source_output.get('reply_subject','')!r}. "
                f"Preview: {(source_output.get('reply_body') or '')[:120]}"
            ),
        )
        db.add(activity)
        db.flush()

        log.info(
            "campaign.node.condition.negative_reply.lead_closed",
            execution_id=str(execution.id),
            lead_id=str(lead_id),
            subject=source_output.get("reply_subject"),
        )

    @staticmethod
    def _enrich_with_reply_check(
        *,
        source_output: dict,
        window_minutes: int,
        node_id: str,
        execution_id: str,
        lead_id: str = "",
    ) -> dict:
        """Call the IMAP reply-detection service and merge results.

        Each call is scoped to a single lead's execution so leads never
        interfere with each other.  Passes ``execution_id`` and ``lead_id``
        through to the IMAP service for per-lead log correlation.

        Returns a *copy* of ``source_output`` enriched with:
        ``replied``, ``within_window``, ``replied_at``, ``match_method``,
        ``reply_check_error``.
        """
        from modules.campaign.email_reply_service import check_for_reply
        from datetime import datetime, timezone

        to_address: str = source_output.get("to") or ""
        sent_at_str: str | None = source_output.get("sent_at")
        message_id: str | None = source_output.get("message_id")

        log.info(
            "campaign.node.condition.email_reply_check.start",
            execution_id=execution_id,
            lead_id=lead_id,
            node_id=node_id,
            to=to_address,
            message_id=message_id,
            sent_at=sent_at_str,
            window_minutes=window_minutes,
        )

        if not to_address or not sent_at_str:
            reason = (
                "missing 'to' address" if not to_address
                else "missing 'sent_at' timestamp"
            )
            log.warning(
                "campaign.node.condition.email_reply_check.missing_context",
                execution_id=execution_id,
                lead_id=lead_id,
                node_id=node_id,
                reason=reason,
                has_to=bool(to_address),
                has_sent_at=bool(sent_at_str),
            )
            enriched = dict(source_output)
            enriched.update({
                "replied": False,
                "within_window": False,
                "replied_at": None,
                "match_method": None,
                "reply_check_error": reason,
            })
            return enriched

        try:
            sent_at = datetime.fromisoformat(sent_at_str)
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
        except ValueError:
            log.warning(
                "campaign.node.condition.email_reply_check.bad_sent_at",
                execution_id=execution_id,
                lead_id=lead_id,
                node_id=node_id,
                sent_at=sent_at_str,
            )
            enriched = dict(source_output)
            enriched.update({
                "replied": False,
                "within_window": False,
                "replied_at": None,
                "match_method": None,
                "reply_check_error": f"cannot parse sent_at: {sent_at_str!r}",
            })
            return enriched

        reply_result = check_for_reply(
            to_address=to_address,
            sent_at=sent_at,
            window_minutes=window_minutes,
            message_id=message_id,
            execution_id=execution_id,
            lead_id=lead_id,
        )

        log.info(
            "campaign.node.condition.email_reply_check.result",
            execution_id=execution_id,
            lead_id=lead_id,
            node_id=node_id,
            to=to_address,
            replied=reply_result.get("replied"),
            within_window=reply_result.get("within_window"),
            negative_reply=reply_result.get("negative_reply"),
            replied_at=reply_result.get("replied_at"),
            match_method=reply_result.get("match_method"),
            error=reply_result.get("error"),
        )

        enriched = dict(source_output)
        enriched.update({
            "replied": reply_result.get("replied", False),
            "within_window": reply_result.get("within_window", False),
            "negative_reply": reply_result.get("negative_reply", False),
            "replied_at": reply_result.get("replied_at"),
            "match_method": reply_result.get("match_method"),
            "reply_subject": reply_result.get("reply_subject"),
            "reply_body": reply_result.get("reply_body"),
            "reply_check_error": reply_result.get("error"),
        })
        return enriched

    @staticmethod
    def _emit_cond_eval_activity(
        db: "Session",
        execution: "Execution",
        *,
        condition_type: str,
        result_label: str,
        next_node: str,
    ) -> None:
        """Write a cond_eval LeadActivity row recording a branch decision."""
        import uuid
        from modules.leads.model import ACTIVITY_COND_EVAL, LeadActivity

        ctx = execution.context or {}
        lead_ctx = ctx.get("lead") or {}
        lead_id_raw = lead_ctx.get("id")
        org_id_raw = ctx.get("org_id") or lead_ctx.get("organization_id")

        if not lead_id_raw or not org_id_raw:
            return

        try:
            lead_id = uuid.UUID(str(lead_id_raw))
            org_id = uuid.UUID(str(org_id_raw))
        except ValueError:
            return

        activity = LeadActivity(
            organization_id=org_id,
            lead_id=lead_id,
            activity_type=ACTIVITY_COND_EVAL,
            notes=(
                f"Condition {condition_type} -> {result_label}; "
                f"next node: {next_node}"
            ),
        )
        db.add(activity)
        try:
            db.flush()
        except Exception as exc:
            log.warning(
                "campaign.node.condition.cond_eval_log_failed",
                execution_id=str(execution.id),
                error=str(exc),
            )
            db.rollback()

    @staticmethod
    def _emit_reply_received_activity(
        db: "Session",
        execution: "Execution",
        source_output: dict,
    ) -> None:
        """Write a reply_recv LeadActivity row when a reply is confirmed.

        Runs regardless of which branch (TRUE/FALSE) the workflow takes so
        the lead timeline always records that a reply was received.  Guards
        against duplicate writes by checking for an existing row are omitted
        for simplicity — the activity table allows multiple rows per lead.
        """
        import uuid
        from modules.leads.model import ACTIVITY_REPLY_RECEIVED, LeadActivity

        ctx = execution.context or {}
        lead_ctx = ctx.get("lead") or {}
        lead_id_raw = lead_ctx.get("id")
        org_id_raw = ctx.get("org_id") or lead_ctx.get("organization_id")

        if not lead_id_raw or not org_id_raw:
            return

        try:
            lead_id = uuid.UUID(str(lead_id_raw))
            org_id = uuid.UUID(str(org_id_raw))
        except ValueError:
            return

        activity = LeadActivity(
            organization_id=org_id,
            lead_id=lead_id,
            activity_type=ACTIVITY_REPLY_RECEIVED,
            notes=(
                f"Reply detected via {source_output.get('match_method', 'unknown')}. "
                f"Subject: {source_output.get('reply_subject', '')!r}. "
                f"Preview: {(source_output.get('reply_body') or '')[:120]}"
            ),
        )
        db.add(activity)
        try:
            db.flush()
        except Exception as exc:
            log.warning(
                "campaign.node.condition.reply_activity_log_failed",
                execution_id=str(execution.id),
                error=str(exc),
            )
            db.rollback()

        log.info(
            "campaign.node.condition.reply_recv_activity_written",
            execution_id=str(execution.id),
            lead_id=str(lead_id),
        )

    @staticmethod
    def _fail(
        db: "Session",
        execution: "Execution",
        node_id: str,
        reason: str,
    ) -> NodeResult:
        log.warning(
            "campaign.node.condition.failed",
            execution_id=str(execution.id),
            node_id=node_id,
            reason=reason,
        )
        execution.status = "failed"
        execution.last_failure_reason = reason
        db.flush()
        return NodeResult(
            outcome="failed",
            advance=False,
            output={"error": reason},
        )
