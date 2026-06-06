"""Node handler registry for graph-based campaign workflows.

Usage
-----
Look up a handler class by node type string, instantiate it, and call
``await handler.execute(db, execution, node)``.

    from modules.campaign.node_handlers import NODE_HANDLERS, NodeResult

    handler_class = NODE_HANDLERS.get(node_type)
    if handler_class is None:
        raise ValueError(f"No handler registered for node type '{node_type}'")
    result: NodeResult = await handler_class().execute(db, execution, node)

Extending
---------
To add a new node type, create a module in this package, subclass
:class:`~modules.campaign.node_handlers.base.BaseNodeHandler`, implement
``execute``, and add an entry to :data:`NODE_HANDLERS`.

Only ``CALL`` and ``STOP`` are implemented in Phase 2D.  Email, LinkedIn,
Wait, and Condition nodes are reserved for future phases.
"""

from modules.campaign.node_handlers.base import BaseNodeHandler, NodeResult
from modules.campaign.node_handlers.call_handler import CallNodeHandler
from modules.campaign.node_handlers.condition_handler import ConditionNodeHandler
from modules.campaign.node_handlers.email_handler import EmailNodeHandler
from modules.campaign.node_handlers.linkedin_handler import LinkedInNodeHandler
from modules.campaign.node_handlers.stop_handler import StopNodeHandler
from modules.campaign.node_handlers.wait_handler import WaitNodeHandler

NODE_HANDLERS: dict[str, type[BaseNodeHandler]] = {
    "CALL": CallNodeHandler,
    "WAIT": WaitNodeHandler,
    "EMAIL": EmailNodeHandler,
    "LINKEDIN": LinkedInNodeHandler,
    "CONDITION": ConditionNodeHandler,
    "STOP": StopNodeHandler,
}

__all__ = [
    "BaseNodeHandler",
    "CallNodeHandler",
    "ConditionNodeHandler",
    "EmailNodeHandler",
    "LinkedInNodeHandler",
    "NodeResult",
    "NODE_HANDLERS",
    "StopNodeHandler",
    "WaitNodeHandler",
]
