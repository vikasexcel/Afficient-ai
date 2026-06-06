"""Base class and result type for graph node handlers.

Every concrete handler receives the current execution and its node
configuration dict, runs its logic, and returns a :class:`NodeResult` that
tells the graph executor whether to advance to the next node or halt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from modules.campaign.execution_model import Execution


@dataclass
class NodeResult:
    """The outcome of executing a single graph node.

    Attributes
    ----------
    outcome:
        Semantic result string (``"completed"``, ``"running"``, ``"failed"``,
        ``"TRUE"``, ``"FALSE"``, …).
    advance:
        ``True`` → the graph executor should immediately advance to the next
        node in the same ``run_execution`` call.
        ``False`` → halt here (e.g. waiting for a webhook, or terminal node).
    output:
        Arbitrary JSON-serialisable data produced by the node; stored in
        ``Execution.node_outputs[node_id]``.
    next_node_id:
        When set, the graph executor uses this node id as the next execution
        target instead of automatically following the first outbound edge.
        Used by CONDITION nodes to select a specific branch.  ``None`` means
        normal automatic edge selection.
    """

    outcome: str
    advance: bool
    output: dict = field(default_factory=dict)
    next_node_id: str | None = None


class BaseNodeHandler:
    """Abstract base for all node handlers.

    Subclasses must override :meth:`execute`.  Handlers are stateless;
    instantiate them fresh per-execution.
    """

    async def execute(
        self,
        db: "Session",
        execution: "Execution",
        node: dict,
    ) -> NodeResult:
        raise NotImplementedError(
            f"{type(self).__name__}.execute() is not implemented"
        )
