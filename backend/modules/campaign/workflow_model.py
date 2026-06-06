import uuid

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import BaseModel


class Workflow(BaseModel):
    """A campaign execution plan.

    ``nodes`` and ``edges`` store the graph definition for graph-based
    workflows.  Both default to ``[]`` so legacy linear campaigns (created
    before Phase 2A) remain fully operational without any code changes.

    Schema notes
    ------------
    * nodes : list[dict] — each entry is a node descriptor::

          {"id": "<str>", "type": "<str>", "label": "<str>", "config": {...}}

    * edges : list[dict] — each entry is a directed edge::

          {"id": "<str>", "source": "<str>", "target": "<str>",
           "condition_type": "always"|"outcome_equals"|"outcome_in",
           "condition_value": "<str>" | ["<str>", ...] | null}

    Legacy executions (``Execution.current_node_id IS NULL``) are not
    affected by the presence of these columns.
    """

    __tablename__ = "workflows"

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"))

    state: Mapped[str] = mapped_column(String(50), default="draft")

    # Graph definition — empty list means "legacy linear workflow".
    nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    edges: Mapped[list] = mapped_column(JSON, nullable=False, default=list)