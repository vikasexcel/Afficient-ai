"""Service layer for execution management.

``ExecutionService`` owns all business rules that touch the ``executions``
table.  It delegates data access to
:class:`~modules.campaign.repository.ExecutionRepository` and is the single
authority for execution construction, status transitions, and node-position
tracking.

Responsibilities
----------------
* Constructing new ``Execution`` ORM objects with correct defaults.
* Surfacing typed accessors used by ``CampaignService`` and the router.
* Status-transition helpers (``update_status``, ``update_current_node``,
  ``update_outputs``).

Out of scope (Phase 2C)
-----------------------
Graph traversal, next-node resolution, edge evaluation.  These are Phase 2D
concerns.  The node-tracking methods (``update_current_node``,
``update_outputs``) are wired up here so they can be called by the Phase 2D
worker without touching this file again.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from common.logging import get_logger
from modules.campaign.execution_model import Execution
from modules.campaign.repository import ExecutionRepository

log = get_logger("campaign.execution_service")


class ExecutionService:

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @staticmethod
    def create_execution(
        db: Session,
        *,
        workflow_id: uuid.UUID,
        lead_id: uuid.UUID | None = None,
        context: dict | None = None,
        current_node_id: str | None = None,
    ) -> Execution:
        """Construct and persist a new queued execution row.

        ``current_node_id=None`` creates a legacy flat execution compatible
        with the existing scheduler and worker.  Phase 2D callers will pass
        the entry-point node id of the workflow graph.
        """
        execution = Execution(
            workflow_id=workflow_id,
            status="queued",
            lead_id=lead_id,
            context=context,
            current_node_id=current_node_id,
        )
        ExecutionRepository.create(db, execution)

        # Write "lead entered workflow" activity for the audit trail.
        ExecutionService._log_wf_activity(db, execution, "wf_start")

        return execution

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_execution(
        db: Session, execution_id: uuid.UUID
    ) -> Execution | None:
        """Return an execution by primary key, or ``None``."""
        return ExecutionRepository.get(db, execution_id)

    @staticmethod
    def get_next_queued_execution(
        db: Session, workflow_id: uuid.UUID
    ) -> Execution | None:
        """Return the oldest queued execution for a workflow (FIFO order).

        Returns ``None`` when no queued execution exists, which the caller
        should treat as "no work" rather than creating a phantom row.
        """
        return ExecutionRepository.get_next_queued(db, workflow_id)

    @staticmethod
    def list_executions(
        db: Session, workflow_id: uuid.UUID
    ) -> list[Execution]:
        """Return all executions for a workflow, oldest first."""
        return ExecutionRepository.list_by_workflow(db, workflow_id)

    # ------------------------------------------------------------------ #
    # Status / node transitions (caller commits)
    # ------------------------------------------------------------------ #

    @staticmethod
    def update_status(
        db: Session, execution: Execution, status: str
    ) -> Execution:
        """Set ``execution.status`` and flush.  Caller commits.

        Intended for Phase 2D graph-aware transitions.  Existing worker and
        retry-engine code mutates ``execution.status`` directly and is not
        changed by this service.
        """
        execution.status = status
        db.flush()
        return execution

    @staticmethod
    def update_current_node(
        db: Session, execution: Execution, node_id: str | None
    ) -> Execution:
        """Advance an execution to a different graph node.

        Pass ``node_id=None`` to clear the node position (e.g. on terminal
        outcome).  Caller commits.
        """
        return ExecutionRepository.update_current_node(db, execution, node_id)

    @staticmethod
    def update_outputs(
        db: Session,
        execution: Execution,
        *,
        node_id: str,
        output: dict,
    ) -> Execution:
        """Record the output produced by a specific graph node.

        Merges into the existing ``node_outputs`` map so multiple nodes can
        accumulate results without overwriting each other.  Caller commits.
        """
        return ExecutionRepository.update_outputs(db, execution, node_id, output)

    # ------------------------------------------------------------------ #
    # Graph advancement  (Phase 2D)
    # ------------------------------------------------------------------ #

    @staticmethod
    def advance_execution(
        db: Session,
        execution: Execution,
        workflow,
        current_node_id: str,
        output: dict,
    ) -> Execution:
        """Persist a node's output and advance the execution pointer.

        Responsibilities
        ----------------
        1. Save *output* into ``execution.node_outputs[current_node_id]``.
        2. Resolve the outbound edges of *current_node_id*.
        3. If a next node exists: update ``execution.current_node_id`` and
           flush — the graph run-loop will execute that node next.
        4. If no next node (terminal): mark the execution ``completed``
           (unless it was already set to a terminal status by the node
           handler itself, e.g. by ``StopNodeHandler``).

        Caller is responsible for the final ``db.commit()``.
        """
        from modules.campaign.workflow_service import WorkflowService

        if output:
            ExecutionRepository.update_outputs(
                db, execution, current_node_id, output
            )

        next_nodes = WorkflowService.get_next_nodes(workflow, current_node_id)

        if next_nodes:
            ExecutionRepository.update_current_node(
                db, execution, next_nodes[0]["id"]
            )
        else:
            if execution.status not in ("completed", "failed", "exhausted"):
                execution.status = "completed"
                execution.retry_status = "completed"
                ExecutionService._log_wf_activity(db, execution, "wf_done")
            db.flush()

        return execution

    # ------------------------------------------------------------------ #
    # Internal activity logging
    # ------------------------------------------------------------------ #

    @staticmethod
    def _log_wf_activity(
        db: Session,
        execution: Execution,
        activity_type: str,
        notes: str | None = None,
    ) -> None:
        """Write a LeadActivity row for workflow-level events (wf_start, wf_done)."""
        import uuid as _uuid
        from modules.leads.model import LeadActivity

        ctx = execution.context or {}
        lead_ctx = ctx.get("lead") or {}
        lead_id_raw = (
            execution.lead_id
            or lead_ctx.get("id")
        )
        org_id_raw = ctx.get("org_id") or lead_ctx.get("organization_id")

        if not lead_id_raw or not org_id_raw:
            return
        try:
            lead_id = _uuid.UUID(str(lead_id_raw))
            org_id = _uuid.UUID(str(org_id_raw))
        except ValueError:
            return

        db.add(LeadActivity(
            organization_id=org_id,
            lead_id=lead_id,
            activity_type=activity_type,
            notes=notes,
        ))
        db.flush()
