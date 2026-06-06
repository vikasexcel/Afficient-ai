"""WAIT node handler.

Parks the execution for a configurable duration before continuing to the
next node.  The WAIT node is the only handler that advances the graph
pointer *itself* (before parking) so the execution wakes up ready to run
the node that follows it.

Execution lifecycle
-------------------
1. Handler calculates ``wake_at = now + duration``.
2. Resolves the next node from the workflow's edges.
3. Stamps ``execution.current_node_id`` with that next node's id.
4. Sets ``execution.next_retry_at = wake_at`` and ``status = "queued"``.
5. Returns ``NodeResult(advance=False)`` — the run loop commits and exits.

On the next scheduler tick **after** ``wake_at`` has passed,
:meth:`~modules.campaign.repository.ExecutionRepository.list_queued` (which
filters ``next_retry_at <= now``) includes the execution and the scheduler
dispatches it normally.  The worker then runs the next node (e.g. STOP).

Node config schema
------------------
::

    {
        "id":       "wait_1",
        "type":     "WAIT",
        "duration": 24,
        "unit":     "hours"
    }

Supported ``unit`` values: ``"minutes"``, ``"hours"``, ``"days"``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from common.logging import get_logger
from modules.campaign.node_handlers.base import BaseNodeHandler, NodeResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from modules.campaign.execution_model import Execution

log = get_logger("campaign.node_handlers.wait")

_UNIT_TO_MINUTES: dict[str, int] = {
    "minutes": 1,
    "hours": 60,
    "days": 1440,
}


class WaitNodeHandler(BaseNodeHandler):
    """Park the execution until a timer fires, then continue the graph."""

    async def execute(
        self,
        db: "Session",
        execution: "Execution",
        node: dict,
    ) -> NodeResult:
        from modules.campaign.workflow_model import Workflow
        from modules.campaign.workflow_service import WorkflowService

        node_id: str = node.get("id", "")
        unit = (node.get("unit") or "minutes").strip().lower()
        multiplier = _UNIT_TO_MINUTES.get(unit)

        if multiplier is None:
            reason = f"WAIT node '{node_id}': unknown unit '{unit}'"
            log.warning(
                "campaign.node.wait.bad_unit",
                execution_id=str(execution.id),
                node_id=node_id,
                unit=unit,
            )
            execution.status = "failed"
            execution.last_failure_reason = reason
            db.flush()
            return NodeResult(
                outcome="failed",
                advance=False,
                output={"error": reason},
            )

        try:
            duration = int(node.get("duration", 0))
        except (TypeError, ValueError):
            duration = 0

        # Zero or negative duration — skip the wait and advance immediately.
        if duration <= 0:
            log.debug(
                "campaign.node.wait.skipped",
                execution_id=str(execution.id),
                node_id=node_id,
                duration=duration,
            )
            return NodeResult(
                outcome="completed",
                advance=True,
                output={"skipped": True, "reason": "duration <= 0"},
            )

        total_minutes = duration * multiplier
        now = datetime.now(timezone.utc)
        wake_at = now + timedelta(minutes=total_minutes)

        # Resolve the next node so the execution wakes up ready to execute it.
        workflow = db.get(Workflow, execution.workflow_id)
        if workflow is None:
            reason = f"workflow {execution.workflow_id} not found"
            execution.status = "failed"
            execution.last_failure_reason = reason
            db.flush()
            return NodeResult(
                outcome="failed",
                advance=False,
                output={"error": reason},
            )

        next_nodes = WorkflowService.get_next_nodes(workflow, node_id)

        if not next_nodes:
            # WAIT is a terminal node — mark completed and exit.
            log.info(
                "campaign.node.wait.terminal",
                execution_id=str(execution.id),
                node_id=node_id,
            )
            execution.status = "completed"
            execution.retry_status = "completed"
            db.flush()
            return NodeResult(
                outcome="completed",
                advance=False,
                output={"wake_at": wake_at.isoformat()},
            )

        next_node_id = next_nodes[0]["id"]

        # Advance pointer NOW so the execution wakes at the correct node.
        execution.current_node_id = next_node_id
        # Park: scheduler skips this execution until next_retry_at has passed.
        execution.next_retry_at = wake_at
        execution.status = "queued"
        execution.retry_status = "pending"
        db.flush()

        log.info(
            "campaign.node.wait.parked",
            execution_id=str(execution.id),
            node_id=node_id,
            next_node_id=next_node_id,
            duration_minutes=total_minutes,
            wake_at=wake_at.isoformat(),
        )

        return NodeResult(
            outcome="waiting",
            advance=False,
            output={
                "wake_at": wake_at.isoformat(),
                "duration_minutes": total_minutes,
                "next_node_id": next_node_id,
            },
        )
