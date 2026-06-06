"""STOP node handler.

A STOP node is a terminal node — it immediately marks the execution as
``completed`` and returns ``advance=False`` so the graph executor exits the
run loop.  There are no outbound edges from a STOP node; the graph executor
will find no next nodes regardless, but returning ``advance=False`` makes
the intent explicit and avoids an unnecessary graph traversal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.logging import get_logger
from modules.campaign.node_handlers.base import BaseNodeHandler, NodeResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from modules.campaign.execution_model import Execution

log = get_logger("campaign.node_handlers.stop")


class StopNodeHandler(BaseNodeHandler):
    """Immediately complete the execution."""

    async def execute(
        self,
        db: "Session",
        execution: "Execution",
        node: dict,
    ) -> NodeResult:
        execution.status = "completed"
        execution.retry_status = "completed"
        db.flush()

        log.info(
            "campaign.node.stop",
            execution_id=str(execution.id),
            node_id=node.get("id"),
        )

        return NodeResult(outcome="completed", advance=False)
