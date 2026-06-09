"""Service layer for workflow management.

``WorkflowService`` owns all business rules that touch the ``workflows`` table.
It delegates data access to :class:`~modules.campaign.repository.WorkflowRepository`
and is the single authority for workflow construction, state transitions, graph
validation, and graph versioning.

Responsibilities
----------------
* Constructing new ``Workflow`` ORM objects with correct defaults.
* Surfacing typed accessors used by ``CampaignService`` and the router.
* Validating graph structure (``nodes`` / ``edges``) before it is persisted.
* State-transition helpers (``update_state``, ``update_graph``).
* Versioning — automatically creating/restoring
  :class:`~modules.campaign.workflow_version_model.WorkflowVersion` records
  whenever the graph definition changes (Phase 3C).

Out of scope (Phase 2C)
-----------------------
Graph traversal, node execution, edge evaluation.  These are Phase 2D concerns.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from common.logging import get_logger
from modules.campaign.repository import WorkflowRepository
from modules.campaign.workflow_model import Workflow
from modules.campaign.workflow_version_model import WorkflowVersion
from modules.campaign.workflow_version_repository import WorkflowVersionRepository

log = get_logger("campaign.workflow_service")


class WorkflowService:

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @staticmethod
    def create_workflow(
        db: Session,
        *,
        campaign_id: uuid.UUID,
        state: str = "active",
        nodes: list | None = None,
        edges: list | None = None,
        created_by: uuid.UUID | None = None,
    ) -> Workflow:
        """Construct and persist a new workflow row.

        ``nodes`` and ``edges`` default to ``[]`` (legacy linear workflow).
        Callers that supply a graph must have validated it with
        :meth:`validate_workflow` first, or pass ``nodes``/``edges`` through
        :meth:`create_workflow_from_graph` which validates automatically.

        When a non-empty graph is supplied, version 1 is automatically created.
        """
        _nodes = nodes or []
        _edges = edges or []
        workflow = Workflow(
            campaign_id=campaign_id,
            state=state,
            nodes=_nodes,
            edges=_edges,
        )
        WorkflowRepository.create(db, workflow)

        # Create version 1 automatically for graph workflows.
        if _nodes:
            WorkflowVersionRepository.create_version(
                db,
                workflow_id=workflow.id,
                version=1,
                nodes=_nodes,
                edges=_edges,
                created_by=created_by,
            )
            log.debug(
                "workflow.version.created",
                workflow_id=str(workflow.id),
                version=1,
            )

        log.debug(
            "workflow.created",
            campaign_id=str(campaign_id),
            workflow_id=str(workflow.id),
            state=state,
            has_graph=bool(_nodes),
        )
        return workflow

    @staticmethod
    def create_workflow_from_graph(
        db: Session,
        *,
        campaign_id: uuid.UUID,
        nodes: list,
        edges: list,
        state: str = "active",
        created_by: uuid.UUID | None = None,
    ) -> Workflow:
        """Validate the graph then create a workflow that holds it.

        Raises :class:`ValueError` if the graph structure is invalid.
        """
        WorkflowService.validate_workflow(nodes, edges)
        return WorkflowService.create_workflow(
            db,
            campaign_id=campaign_id,
            state=state,
            nodes=nodes,
            edges=edges,
            created_by=created_by,
        )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_workflow(
        db: Session, workflow_id: uuid.UUID
    ) -> Workflow | None:
        """Return a workflow by primary key, or ``None``."""
        return WorkflowRepository.get(db, workflow_id)

    @staticmethod
    def get_active_workflow(
        db: Session,
        campaign_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> Workflow | None:
        """Return the single active workflow for a campaign.

        Pass ``lock=True`` to acquire a ``SELECT … FOR UPDATE SKIP LOCKED``
        row-lock — used by the idempotency guard in ``CampaignService.activate``
        to prevent duplicate activation under concurrent requests.
        """
        return WorkflowRepository.get_active_for_campaign(
            db, campaign_id, lock=lock
        )

    @staticmethod
    def get_paused_workflow(
        db: Session, campaign_id: uuid.UUID
    ) -> Workflow | None:
        """Return the most-recently paused workflow for a campaign."""
        return WorkflowRepository.get_paused_for_campaign(db, campaign_id)

    # ------------------------------------------------------------------ #
    # State transitions
    # ------------------------------------------------------------------ #

    @staticmethod
    def update_state(
        db: Session, workflow: Workflow, state: str
    ) -> Workflow:
        """Set ``workflow.state`` and flush.  Caller commits."""
        return WorkflowRepository.update_state(db, workflow, state)

    @staticmethod
    def update_graph(
        db: Session,
        workflow: Workflow,
        *,
        nodes: list,
        edges: list,
        created_by: uuid.UUID | None = None,
    ) -> Workflow:
        """Validate then replace the graph definition on a workflow.

        Raises :class:`ValueError` if the graph structure is invalid.
        Caller commits after this returns.

        A new :class:`~modules.campaign.workflow_version_model.WorkflowVersion`
        record is created automatically **only when the graph actually changes**.
        Submitting an identical graph (same nodes and edges) is a no-op that
        returns the workflow unchanged without bumping the version counter.
        """
        WorkflowService.validate_workflow(nodes, edges)

        if not WorkflowService._graph_changed(workflow, nodes, edges):
            log.debug(
                "workflow.graph.unchanged",
                workflow_id=str(workflow.id),
            )
            return workflow

        next_v = WorkflowVersionRepository.next_version_number(db, workflow.id)
        WorkflowVersionRepository.create_version(
            db,
            workflow_id=workflow.id,
            version=next_v,
            nodes=nodes,
            edges=edges,
            created_by=created_by,
        )
        updated = WorkflowRepository.update_graph(db, workflow, nodes, edges)
        log.info(
            "workflow.graph.updated",
            workflow_id=str(workflow.id),
            version=next_v,
            node_count=len(nodes),
            edge_count=len(edges),
        )
        return updated

    # ------------------------------------------------------------------ #
    # Versioning helpers  (Phase 3C)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _graph_changed(
        workflow: Workflow,
        new_nodes: list,
        new_edges: list,
    ) -> bool:
        """Return True when *new_nodes* / *new_edges* differ from the current graph.

        Comparison is done via canonical JSON serialisation (dict keys sorted,
        list order preserved) so reordering dict keys inside a node/edge dict
        is treated as no-change, but reordering the list of nodes/edges itself
        is treated as a change.
        """
        def _canonical(obj: list) -> str:
            return json.dumps(obj, sort_keys=True)

        return (
            _canonical(new_nodes) != _canonical(workflow.nodes or [])
            or _canonical(new_edges) != _canonical(workflow.edges or [])
        )

    @staticmethod
    def list_versions(
        db: Session,
        workflow_id: uuid.UUID,
    ) -> list[WorkflowVersion]:
        """Return all version records for a workflow, newest-first."""
        return WorkflowVersionRepository.list_versions(db, workflow_id)

    @staticmethod
    def get_version(
        db: Session,
        workflow_id: uuid.UUID,
        version: int,
    ) -> WorkflowVersion | None:
        """Return a specific version snapshot, or ``None`` if not found."""
        return WorkflowVersionRepository.get_version(db, workflow_id, version)

    @staticmethod
    def restore_version(
        db: Session,
        workflow: Workflow,
        version: int,
        *,
        created_by: uuid.UUID | None = None,
    ) -> tuple[Workflow, WorkflowVersion]:
        """Restore a workflow's graph to the state captured in *version*.

        Flow
        ----
        1. Load the version snapshot — raises :class:`LookupError` if absent.
        2. Validate the snapshot graph — raises :class:`ValueError` if corrupt.
        3. Create a **new** version record (current_max + 1) with the restored
           content so the operation is auditable and history is never destroyed.
        4. Overwrite the workflow's ``nodes`` / ``edges``.

        Returns
        -------
        (updated_workflow, new_version_record)
            The workflow with its graph replaced and the newly created version
            record (whose ``version`` number is the new head).

        Caller must commit.
        """
        snapshot = WorkflowVersionRepository.get_version(db, workflow.id, version)
        if snapshot is None:
            raise LookupError(
                f"workflow {workflow.id} has no version {version}"
            )

        # Guard against a corrupt snapshot reaching the execution engine.
        errors, _ = WorkflowService.validate_graph_detailed(
            snapshot.nodes or [], snapshot.edges or []
        )
        if errors:
            raise ValueError(
                f"snapshot at version {version} failed validation: {errors[0]}"
            )

        next_v = WorkflowVersionRepository.next_version_number(db, workflow.id)
        new_record = WorkflowVersionRepository.create_version(
            db,
            workflow_id=workflow.id,
            version=next_v,
            nodes=snapshot.nodes or [],
            edges=snapshot.edges or [],
            created_by=created_by,
        )
        WorkflowVersionRepository.restore_version(db, workflow, snapshot)

        log.info(
            "workflow.version.restored",
            workflow_id=str(workflow.id),
            restored_from=version,
            new_version=next_v,
        )
        return workflow, new_record

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Graph traversal helpers  (Phase 2D)
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_entry_node(workflow: Workflow) -> dict:
        """Return the entry node — the unique node with no inbound edges.

        Raises :class:`ValueError` when:
        * The workflow has no nodes (legacy linear workflow).
        * Every node has at least one inbound edge (cycle with no root).
        """
        nodes: list[dict] = workflow.nodes or []
        edges: list[dict] = workflow.edges or []

        if not nodes:
            raise ValueError(
                f"workflow {workflow.id} has no nodes; "
                "cannot determine entry node"
            )

        target_ids: set[str] = {e["target"] for e in edges}
        entry_nodes = [n for n in nodes if n["id"] not in target_ids]

        if not entry_nodes:
            raise ValueError(
                f"workflow {workflow.id} has no entry node "
                "(all nodes have at least one inbound edge)"
            )

        return entry_nodes[0]

    @staticmethod
    def get_next_nodes(workflow: Workflow, current_node_id: str) -> list[dict]:
        """Return ordered list of nodes reachable via outbound edges.

        Returns an empty list when ``current_node_id`` is a terminal node
        (no outbound edges) or does not exist in the workflow.
        """
        nodes: list[dict] = workflow.nodes or []
        edges: list[dict] = workflow.edges or []

        node_map: dict[str, dict] = {n["id"]: n for n in nodes}
        target_ids = [
            e["target"] for e in edges if e["source"] == current_node_id
        ]
        return [node_map[tid] for tid in target_ids if tid in node_map]

    # ------------------------------------------------------------------ #
    # Condition evaluation helpers  (Phase 2G)
    # ------------------------------------------------------------------ #

    #: Mapping from condition-type string → callable(output_dict) → bool.
    #: ``output_dict`` is the ``node_outputs[source_node_id]`` slice for the
    #: node whose result is being inspected.
    _CONDITION_EVALUATORS: dict = {
        # EMAIL node stores {"sent": True/False, ...}
        "EMAIL_SENT":     staticmethod(lambda o: bool(o.get("sent"))),
        "EMAIL_FAILED":   staticmethod(lambda o: not bool(o.get("sent"))),
        # EMAIL_REPLIED: checks whether any reply was received, regardless of
        # *when* it arrived.  The condition_handler sets "replied" = True via
        # the inbound webhook path (instant) or IMAP fallback (polled).
        # Previously this read "within_window" which silently dropped replies
        # that arrived after the window expired — those are now TRUE branches.
        "EMAIL_REPLIED":    staticmethod(lambda o: bool(o.get("replied"))),
        # True when the reply body contains opt-out / negative phrases.
        # Set by the inbound webhook handler or the IMAP fallback.
        "NEGATIVE_REPLY":  staticmethod(lambda o: bool(o.get("negative_reply"))),
        # CALL node stores {"outcome": "completed"/"failed"/"running", ...}
        "CALL_COMPLETED": staticmethod(lambda o: o.get("outcome") == "completed"),
        "CALL_FAILED":    staticmethod(
            lambda o: o.get("outcome") in ("failed", "exhausted")
        ),
    }

    @staticmethod
    def evaluate_condition(
        *,
        condition_type: str,
        source_output: dict,
    ) -> bool:
        """Evaluate a Phase 2G condition against a node's stored output.

        Parameters
        ----------
        condition_type:
            One of ``EMAIL_SENT``, ``EMAIL_FAILED``, ``EMAIL_REPLIED``,
            ``NEGATIVE_REPLY``,
            ``CALL_COMPLETED``, ``CALL_FAILED`` (case-insensitive).
        source_output:
            ``execution.node_outputs[source_node_id]`` — the dict produced
            by the source node when it ran.

        Returns
        -------
        bool
            ``True`` when the condition matches, ``False`` otherwise.

        Raises
        ------
        ValueError
            When ``condition_type`` is not recognised.
        """
        key = (condition_type or "").upper()
        evaluator = WorkflowService._CONDITION_EVALUATORS.get(key)
        if evaluator is None:
            supported = ", ".join(sorted(WorkflowService._CONDITION_EVALUATORS))
            raise ValueError(
                f"unknown condition type '{condition_type}'; "
                f"supported: {supported}"
            )
        return bool(evaluator(source_output or {}))

    @staticmethod
    def get_condition_target(
        workflow: Workflow,
        condition_node_id: str,
        *,
        condition_result: bool,
    ) -> dict | None:
        """Return the target node for the matching conditional edge.

        Each outbound edge of a CONDITION node carries a ``"condition"``
        field: ``"TRUE"`` or ``"FALSE"``.  The edge whose label matches
        *condition_result* is selected; if no labelled edge matches, the
        first unlabelled edge (default branch) is used as a fallback.

        Returns ``None`` when no suitable edge is found.
        """
        nodes: list[dict] = workflow.nodes or []
        edges: list[dict] = workflow.edges or []
        node_map: dict[str, dict] = {n["id"]: n for n in nodes}

        outbound = [e for e in edges if e["source"] == condition_node_id]
        label = "TRUE" if condition_result else "FALSE"

        # 1. Exact match: edge labelled TRUE/FALSE.
        for edge in outbound:
            if (edge.get("condition") or "").upper() == label:
                return node_map.get(edge["target"])

        # 2. Default fallback: first edge with no condition label.
        for edge in outbound:
            if not edge.get("condition"):
                return node_map.get(edge["target"])

        return None

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    #: Node types supported by the execution engine.
    VALID_NODE_TYPES: frozenset[str] = frozenset(
        {"CALL", "WAIT", "EMAIL", "LINKEDIN", "CONDITION", "STOP"}
    )

    @staticmethod
    def validate_graph_detailed(
        nodes: list,
        edges: list,
    ) -> tuple[list[str], list[str]]:
        """Run all graph validation rules and return ``(errors, warnings)``.

        Unlike :meth:`validate_workflow`, this method **collects every
        violation** rather than stopping at the first one.  It is used by the
        ``POST /workflow/validate`` API endpoint.

        Rules (errors = blocking)
        -------------------------
        * ``nodes`` and ``edges`` must be lists.
        * Every node must be a dict with a unique, non-empty ``"id"`` and a
          recognised ``"type"``.
        * Every edge must be a dict with a unique, non-empty ``"id"``,
          ``"source"``, and ``"target"`` referencing valid node IDs.
        * No self-loop edges (``source == target``).
        * Exactly one entry node (a node with no inbound edges).
        * CONDITION nodes must have at least one TRUE outbound edge and at
          least one FALSE outbound edge.
        * STOP nodes must have no outbound edges.
        * Every node must be reachable from the entry node (no orphans).

        Warnings (non-blocking)
        -----------------------
        * Multiple entry nodes detected (unusual but not always wrong).
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(nodes, list):
            errors.append("'nodes' must be a list")
            return errors, warnings
        if not isinstance(edges, list):
            errors.append("'edges' must be a list")
            return errors, warnings

        # Empty graph = legacy linear workflow — always structurally valid.
        if not nodes and not edges:
            return errors, warnings

        # ── node structure ──────────────────────────────────────────────
        node_ids: set[str] = set()
        node_map: dict[str, dict] = {}
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(f"nodes[{idx}] must be a dict")
                continue
            nid = node.get("id") or ""
            if not nid:
                errors.append(f"nodes[{idx}] missing non-empty 'id'")
                continue
            ntype = (node.get("type") or "").upper()
            if not ntype:
                errors.append(f"node '{nid}' missing 'type'")
            elif ntype not in WorkflowService.VALID_NODE_TYPES:
                errors.append(
                    f"node '{nid}' has unknown type '{ntype}'; "
                    f"valid types: {', '.join(sorted(WorkflowService.VALID_NODE_TYPES))}"
                )
            if nid in node_ids:
                errors.append(f"duplicate node id '{nid}'")
            else:
                node_ids.add(nid)
                node_map[nid] = {**node, "type": ntype}

        # ── edge structure ──────────────────────────────────────────────
        edge_ids: set[str] = set()
        # source → set of condition labels on outbound edges
        outbound_conditions: dict[str, set[str]] = {}
        # set of node IDs that appear as edge targets
        target_ids: set[str] = set()

        for idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                errors.append(f"edges[{idx}] must be a dict")
                continue
            eid = edge.get("id") or ""
            if not eid:
                errors.append(f"edges[{idx}] missing non-empty 'id'")
                continue
            src = edge.get("source") or ""
            tgt = edge.get("target") or ""
            if not src:
                errors.append(f"edge '{eid}' missing 'source'")
            elif src not in node_ids:
                errors.append(
                    f"edge '{eid}' source '{src}' is not a known node id"
                )
            if not tgt:
                errors.append(f"edge '{eid}' missing 'target'")
            elif tgt not in node_ids:
                errors.append(
                    f"edge '{eid}' target '{tgt}' is not a known node id"
                )
            if eid in edge_ids:
                errors.append(f"duplicate edge id '{eid}'")
            else:
                edge_ids.add(eid)

            if src and tgt and src in node_ids and tgt in node_ids:
                if src == tgt:
                    errors.append(
                        f"edge '{eid}' is a self-loop (source == target == '{src}')"
                    )
                else:
                    target_ids.add(tgt)
                    cond = (edge.get("condition") or "").upper() or None
                    outbound_conditions.setdefault(src, set()).add(cond)

        # Stop further analysis when structural basics are broken.
        if errors:
            return errors, warnings

        # ── entry node ──────────────────────────────────────────────────
        entry_nodes = [n for n in node_map if n not in target_ids]
        if not entry_nodes:
            errors.append(
                "no entry node found — every node has at least one inbound "
                "edge (possible cycle)"
            )
        elif len(entry_nodes) > 1:
            warnings.append(
                f"multiple entry nodes found: {entry_nodes}; "
                "only the first will be used as the graph entry point"
            )

        # ── CONDITION node rules ────────────────────────────────────────
        for nid, node in node_map.items():
            if node["type"] != "CONDITION":
                continue
            labels = outbound_conditions.get(nid) or set()
            if "TRUE" not in labels:
                errors.append(
                    f"CONDITION node '{nid}' has no outbound edge labelled "
                    "'TRUE' — add an edge with condition='TRUE'"
                )
            if "FALSE" not in labels:
                errors.append(
                    f"CONDITION node '{nid}' has no outbound edge labelled "
                    "'FALSE' — add an edge with condition='FALSE'"
                )

        # ── STOP node rules ─────────────────────────────────────────────
        for nid, node in node_map.items():
            if node["type"] != "STOP":
                continue
            if nid in outbound_conditions:
                errors.append(
                    f"STOP node '{nid}' has outbound edges — STOP must be "
                    "a terminal node with no outbound connections"
                )

        # ── orphan detection (BFS from entry) ───────────────────────────
        if entry_nodes and not errors:
            # Build adjacency list
            adj: dict[str, list[str]] = {n: [] for n in node_map}
            for edge in edges:
                src = edge.get("source", "")
                tgt = edge.get("target", "")
                if src in adj:
                    adj[src].append(tgt)

            visited: set[str] = set()
            queue = [entry_nodes[0]]
            while queue:
                cur = queue.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                queue.extend(adj.get(cur, []))

            orphans = set(node_map) - visited
            for oid in sorted(orphans):
                warnings.append(
                    f"node '{oid}' is unreachable from the entry node — "
                    "it will never be executed"
                )

        return errors, warnings

    @staticmethod
    def validate_workflow(nodes: list, edges: list) -> None:
        """Validate ``nodes`` / ``edges`` and raise :class:`ValueError` on violation.

        Delegates to :meth:`validate_graph_detailed` and raises on the first
        error found.  An empty graph (``nodes=[]``, ``edges=[]``) is valid and
        represents a legacy linear workflow.
        """
        if not nodes and not edges:
            return  # legacy linear workflow — always valid

        errors, _ = WorkflowService.validate_graph_detailed(nodes, edges)
        if errors:
            raise ValueError(errors[0])
