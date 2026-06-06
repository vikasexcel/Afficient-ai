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

Fields
~~~~~~
``condition_type``
    One of ``EMAIL_SENT``, ``EMAIL_FAILED``, ``CALL_COMPLETED``,
    ``CALL_FAILED`` (case-insensitive).

``source_node``
    The ``id`` of the node whose output is inspected.  The handler reads
    ``execution.node_outputs[source_node]`` as the evaluation context.

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
        condition_type: str = (node.get("condition_type") or "").strip()
        source_node_id: str = (node.get("source_node") or "").strip()

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
        source_output: dict = node_outputs.get(source_node_id) or {}

        if not node_outputs.get(source_node_id) and source_node_id:
            log.debug(
                "campaign.node.condition.source_empty",
                execution_id=str(execution.id),
                node_id=node_id,
                source_node=source_node_id,
            )
            # Treat missing output as an empty dict — evaluators handle this
            # (e.g. EMAIL_SENT → sent=False when output is absent).

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
