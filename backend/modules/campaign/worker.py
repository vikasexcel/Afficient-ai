"""In-process execution worker.

Runs one campaign-execution synchronously from the request handler. The
worker exists so the same code path can later be moved to Celery (already
in ``requirements.txt``) without changing callers.

This module replaces the legacy ``AIService.execute`` shim (which was
removed during the GPT-4o refactor) with a direct call into the modern
:class:`~modules.ai.openai_client.OpenAIClient`.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx

from common.logging import get_logger
from config.settings import settings
from modules.ai.dependencies import get_openai
from modules.ai.schema import ChatMessage, MessageRole
from modules.campaign.execution_model import Execution
from modules.campaign.retry import process_outcome

log = get_logger("campaign.worker")


def _campaign_configs(db, execution: Execution) -> tuple[dict | None, dict | None]:
    """Resolve the owning campaign's ``retry_config`` + ``voicemail_config``.

    Returns ``(None, None)`` when no campaign is found so the retry engine
    treats the failure as terminal (legacy behaviour).
    """

    from modules.campaign.model import Campaign
    from modules.campaign.workflow_model import Workflow

    workflow = db.get(Workflow, execution.workflow_id)
    if workflow is None:
        return None, None
    campaign = db.get(Campaign, workflow.campaign_id)
    if campaign is None:
        return None, None
    return campaign.retry_config, campaign.voicemail_config


def _campaign_retry_config(db, execution: Execution) -> dict | None:
    """Backwards-compatible shim returning just the retry config."""

    return _campaign_configs(db, execution)[0]


_EXECUTION_SYSTEM_PROMPT = (
    "You are the campaign execution worker for Aifficient. Given the "
    "workflow context below, output a short JSON object summarising "
    "what the next call attempt should do. Always return valid JSON."
)


def _is_dial_candidate(execution: Execution) -> bool:
    """True when the execution represents a campaign lead that must be dialed.

    Lead executions carry a ``lead`` dict in their frozen ``context`` (set by
    :meth:`CampaignService._enqueue_leads`). Generic executions (e.g. the
    legacy ``/campaigns/execute`` single-shot flow) have no lead and are *not*
    dial candidates — they keep the in-process LLM-plan behaviour.
    """

    ctx = execution.context or {}
    return bool(ctx.get("lead"))


def _call_node_config(node: dict | None) -> dict:
    if not node:
        return {}
    cfg = node.get("config") or {}
    return cfg if isinstance(cfg, dict) else {}


def _call_node_value(node: dict | None, key: str) -> str:
    if not node:
        return ""
    cfg = _call_node_config(node)
    return str(cfg.get(key) or node.get(key) or "").strip()


def _uuid_or_none(value) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _campaign_dial_context(
    db,
    execution: Execution,
    node: dict | None = None,
) -> dict | None:
    """Resolve everything needed to place a real outbound call for a lead.

    Returns ``None`` when the execution can't be dialled (no phone, no
    playbook, or no owning campaign/org).  Graph CALL nodes may carry a
    ``to_number`` override and ``playbook_id`` in their config; those are used
    when the campaign-level fields are absent.
    """

    from modules.campaign.model import Campaign
    from modules.campaign.workflow_model import Workflow

    ctx = execution.context or {}
    lead = ctx.get("lead") or {}
    phone = _call_node_value(node, "to_number") or (lead.get("phone") or "").strip()
    if not phone:
        return None

    workflow = db.get(Workflow, execution.workflow_id)
    if workflow is None:
        return None
    campaign = db.get(Campaign, workflow.campaign_id)
    if campaign is None:
        return None
    playbook_id = campaign.playbook_id or _uuid_or_none(
        _call_node_value(node, "playbook_id")
    )
    if not playbook_id:
        return None

    # ``Campaign`` has no ``created_by`` column (only ``organization_id``); the
    # telephony call is attributed at the org level. ``created_by`` is optional
    # on ``initiate_outbound`` so we pass ``None`` for campaign-originated calls.
    return {
        "to_number": phone,
        "organization_id": campaign.organization_id,
        "created_by": None,
        "campaign_id": campaign.id,
        "playbook_id": playbook_id,
        "lead_id": (
            _uuid_or_none(lead.get("id"))
        ),
        "lead_name": lead.get("name"),
        "lead_phone": phone,
    }


def _fail_dial(
    db,
    execution: Execution,
    reason: str,
) -> None:
    """Mark a dial failure terminal/retryable via the retry engine.

    A dialing failure is a *retryable* outcome (``failed``): the retry engine
    schedules another attempt when the campaign has a ``retry_config`` with
    attempts remaining, otherwise it marks the execution ``failed``. It NEVER
    falls back to the LLM plan, so production dialing failures stay visible.
    """

    retry_config, voicemail_config = _campaign_configs(db, execution)
    process_outcome(
        db,
        execution,
        "failed",
        retry_config=retry_config,
        voicemail_config=voicemail_config,
        failure_reason=reason,
    )


async def _dial_execution(
    db,
    execution: Execution,
    node: dict | None = None,
) -> None:
    """Place a real outbound telephony call for a lead execution.

    Owns the full outcome of the dial attempt and NEVER falls back to the LLM
    stub:

    * Success -> the execution is left ``running``; its terminal outcome is
      reconciled later by the Twilio status webhook via
      ``TelephonyService._reconcile_campaign_execution``.
    * Cannot build a dial context (missing phone / playbook / campaign),
      telephony unavailable, or ``initiate_outbound`` raises -> the execution
      is marked failed (retry scheduled when configured) and the failure is
      logged.
    """

    dial = _campaign_dial_context(db, execution, node=node)
    if dial is None:
        reason = "missing lead phone / playbook / campaign"
        log.warning(
            "CAMPAIGN_DIAL_FAILED",
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            reason=reason,
        )
        _fail_dial(db, execution, reason)
        return

    try:
        from modules.telephony.dependencies import get_telephony_service

        svc = get_telephony_service()
    except Exception as exc:  # telephony not configured / unavailable
        reason = f"telephony unavailable: {exc}"
        log.warning(
            "CAMPAIGN_DIAL_FAILED",
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            campaign_id=str(dial["campaign_id"]),
            reason="telephony_unavailable",
            error=str(exc),
        )
        _fail_dial(db, execution, reason)
        return

    execution.status = "running"
    db.commit()

    try:
        row = await svc.initiate_outbound(
            to_number=dial["to_number"],
            organization_id=dial["organization_id"],
            created_by=dial["created_by"],
            campaign_id=dial["campaign_id"],
            playbook_id=dial["playbook_id"],
            lead_id=dial["lead_id"],
            lead_name=dial["lead_name"],
            lead_phone=dial["lead_phone"],
            execution_id=execution.id,
        )
    except Exception as exc:
        # Twilio / LiveKit origination failed, invalid number, etc. Do NOT run
        # the LLM fallback — surface the failure and let the retry engine decide.
        log.exception(
            "CAMPAIGN_DIAL_EXCEPTION",
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            campaign_id=str(dial["campaign_id"]),
            to=dial["to_number"],
            error=str(exc),
        )
        # Re-fetch in case the originating coroutine left the row detached.
        execution = db.get(Execution, execution.id) or execution
        _fail_dial(db, execution, f"dial failed: {exc}")
        return

    # Stash the call id on the execution so operators can trace it; the
    # outcome arrives asynchronously via the Twilio status webhook.
    merged = dict(execution.context or {})
    merged["telephony_call_id"] = str(row.id)
    execution.context = merged
    db.commit()

    log.info(
        "campaign.execution.dialed",
        execution_id=str(execution.id),
        call_id=str(row.id),
        to=dial["to_number"],
        campaign_id=str(dial["campaign_id"]),
    )


def _internal_dispatch_url() -> str:
    """Absolute URL of the FastAPI origination endpoint."""

    base = (settings.INTERNAL_API_BASE_URL or "").rstrip("/")
    return f"{base}{settings.API_PREFIX}/telephony/calls"


def _build_dial_payload(dial: dict, execution: Execution) -> dict:
    """Serialize a dial context into the ``InitiateCallRequest`` body.

    ``organization_id`` / ``created_by`` / ``execution_id`` are the
    internal-only fields the FastAPI endpoint honors when the request carries
    the service token. Persona / framework / opening line / voice / voicemail
    are intentionally omitted — the playbook (+ campaign ``voicemail_config``)
    is the single source of truth and is resolved server-side from
    ``playbook_id`` / ``campaign_id``.
    """

    def _s(v):
        return str(v) if v is not None else None

    return {
        "to_number": dial["to_number"],
        "organization_id": _s(dial["organization_id"]),
        "created_by": _s(dial["created_by"]),
        "campaign_id": _s(dial["campaign_id"]),
        "playbook_id": _s(dial["playbook_id"]),
        "lead_id": _s(dial["lead_id"]),
        "lead_name": dial["lead_name"],
        "lead_phone": dial["lead_phone"],
        "execution_id": str(execution.id),
    }


def _dispatch_dial_http(
    db,
    execution: Execution,
    node: dict | None = None,
) -> None:
    """Originate a lead call by handing off to the FastAPI process.

    This is the production dial path. It runs **synchronously** in the Celery
    worker thread (no event loop at all), so it can never orphan the AI agent
    task or kill the shared async LiveKit/Redis clients. The FastAPI process
    owns LiveKit room creation, agent startup, STT/LLM/TTS, and SIP bridging
    on its long-running event loop.

    Outcome handling mirrors :func:`_dial_execution`:

    * success -> execution left ``running`` (reconciled later by the Twilio
      status webhook); ``telephony_call_id`` stashed on the context.
    * undiallable lead / dispatch failure -> marked failed via the retry
      engine (retry scheduled when configured). NEVER falls back to the LLM.
    """

    dial = _campaign_dial_context(db, execution, node=node)
    if dial is None:
        reason = "missing lead phone / playbook / campaign"
        log.warning(
            "CAMPAIGN_DISPATCH_FAILED",
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            reason=reason,
        )
        _fail_dial(db, execution, reason)
        return

    payload = _build_dial_payload(dial, execution)
    url = _internal_dispatch_url()

    # Mark running before the request so a crash mid-dispatch leaves the row
    # in a non-terminal state the webhook/retry path can still reconcile.
    execution.status = "running"
    db.commit()

    log.info(
        "CAMPAIGN_DISPATCH_STARTED",
        execution_id=str(execution.id),
        campaign_id=str(dial["campaign_id"]),
        to=dial["to_number"],
        url=url,
    )

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"X-Internal-Token": settings.internal_service_token},
            timeout=settings.CAMPAIGN_DISPATCH_HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        log.warning(
            "CAMPAIGN_DISPATCH_FAILED",
            execution_id=str(execution.id),
            campaign_id=str(dial["campaign_id"]),
            to=dial["to_number"],
            error=str(exc),
        )
        # Re-fetch in case the session was left in an odd state.
        execution = db.get(Execution, execution.id) or execution
        _fail_dial(db, execution, f"dispatch failed: {exc}")
        return

    call_id = body.get("id")
    merged = dict(execution.context or {})
    merged["telephony_call_id"] = call_id
    execution.context = merged
    db.commit()

    log.info(
        "CAMPAIGN_DISPATCH_SUCCEEDED",
        execution_id=str(execution.id),
        campaign_id=str(dial["campaign_id"]),
        call_id=call_id,
        call_sid=body.get("call_sid"),
        room=body.get("room_name"),
        status=body.get("status"),
        to=dial["to_number"],
    )


async def _run_graph_execution(db, execution: Execution, workflow) -> Execution:
    """Drive the node-handler loop for a graph-based execution.

    Each iteration:
    1. Resolves the current node from ``execution.current_node_id``.
    2. Looks up the registered handler for that node's type.
    3. Runs the handler and captures its :class:`~modules.campaign.node_handlers.NodeResult`.
    4. Persists the node's output.
    5. If ``result.advance`` is True: advances the execution pointer to the
       first outbound edge target (or marks it completed when there are none)
       then loops.
    6. If ``result.advance`` is False: commits and exits (blocking node or
       terminal node — e.g. waiting for a webhook, or STOP reached).

    Errors (unknown node id, unregistered type, handler exception) are
    surfaced as ``failed`` executions so the retry engine can respond.
    """

    from modules.campaign.execution_service import ExecutionService
    from modules.campaign.node_handlers import NODE_HANDLERS
    from modules.campaign.workflow_service import WorkflowService

    while True:
        node_id = execution.current_node_id
        if node_id is None:
            try:
                entry = WorkflowService.get_entry_node(workflow)
                node_id = entry["id"]
                ExecutionService.update_current_node(db, execution, node_id)
            except ValueError as exc:
                log.warning(
                    "graph.no_entry_node",
                    execution_id=str(execution.id),
                    workflow_id=str(workflow.id),
                    error=str(exc),
                )
                execution.status = "failed"
                execution.last_failure_reason = str(exc)
                db.commit()
                return execution

        node = next(
            (n for n in (workflow.nodes or []) if n["id"] == node_id), None
        )
        if node is None:
            reason = f"node '{node_id}' not found in workflow graph"
            log.warning(
                "graph.node_not_found",
                execution_id=str(execution.id),
                workflow_id=str(workflow.id),
                node_id=node_id,
            )
            execution.status = "failed"
            execution.last_failure_reason = reason
            db.commit()
            return execution

        node_type = (node.get("type") or "").upper()
        handler_class = NODE_HANDLERS.get(node_type)
        if handler_class is None:
            reason = f"no handler registered for node type '{node_type}'"
            log.warning(
                "graph.unknown_node_type",
                execution_id=str(execution.id),
                workflow_id=str(workflow.id),
                node_id=node_id,
                node_type=node_type,
            )
            execution.status = "failed"
            execution.last_failure_reason = reason
            db.commit()
            return execution

        log.info(
            "graph.node.executing",
            execution_id=str(execution.id),
            workflow_id=str(workflow.id),
            node_id=node_id,
            node_type=node_type,
        )

        if (
            node_type == "CALL"
            and settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED
            and _is_dial_candidate(execution)
            and settings.CAMPAIGN_DISPATCH_VIA_HTTP
        ):
            _dispatch_dial_http(db, execution, node=node)
            return execution

        result = await handler_class().execute(db, execution, node)

        if result.output:
            ExecutionService.update_outputs(
                db, execution, node_id=node_id, output=result.output
            )

        if not result.advance:
            db.commit()
            return execution

        if result.next_node_id is not None:
            # Handler explicitly chose the next node (e.g. CONDITION branching).
            # Outputs were already saved above; just update the pointer.
            ExecutionService.update_current_node(
                db, execution, result.next_node_id
            )
        else:
            # Normal advance — follow the first outbound edge (or mark
            # completed when there are none).
            ExecutionService.advance_execution(
                db, execution, workflow, node_id, result.output
            )

        if execution.status in ("completed", "failed", "exhausted"):
            db.commit()
            return execution
        # Continue loop with updated execution.current_node_id.


def _dispatch_graph_execution(db, execution: Execution, workflow) -> None:
    """Synchronous (Celery-safe) dispatcher for graph-based executions.

    For CALL nodes that require real telephony over HTTP the existing
    :func:`_dispatch_dial_http` synchronous path is reused — the FastAPI
    process owns the AI-agent event loop.  Everything else (non-telephony
    CALL, STOP, or any other immediate node) is handled via the async
    graph runner on a short-lived event loop.
    """

    from modules.campaign.workflow_service import WorkflowService

    node_id = execution.current_node_id
    if node_id is None:
        try:
            node_id = WorkflowService.get_entry_node(workflow)["id"]
        except ValueError:
            log.warning(
                "graph.dispatch.no_entry_node",
                execution_id=str(execution.id),
                workflow_id=str(workflow.id),
            )
            return

    node = next(
        (n for n in (workflow.nodes or []) if n["id"] == node_id), None
    )
    node_type = (node.get("type") or "").upper() if node else ""

    if (
        node_type == "CALL"
        and settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED
        and _is_dial_candidate(execution)
        and settings.CAMPAIGN_DISPATCH_VIA_HTTP
    ):
        _dispatch_dial_http(db, execution, node=node)
        return

    asyncio.run(_run_graph_execution(db, execution, workflow))


def dispatch_execution(db, execution: Execution) -> None:
    """Scheduler dispatch entry point (synchronous, Celery-safe).

    * Graph-based executions (``workflow.nodes`` is non-empty) are routed to
      :func:`_dispatch_graph_execution` which handles the CALL-over-HTTP
      fast path and falls back to the async graph runner for everything else.
    * Legacy dial-candidate lead executions are originated by the FastAPI
      process over authenticated internal HTTP (default) so the AI agent
      lifecycle is tied to the long-running uvicorn event loop.
    * Everything else runs through ``run_execution`` on a short-lived loop.
    """

    from modules.campaign.workflow_model import Workflow as _Workflow

    workflow = db.get(_Workflow, execution.workflow_id)
    if workflow is not None and workflow.nodes:
        _dispatch_graph_execution(db, execution, workflow)
        return

    # --- Legacy path (unchanged) ---
    is_dial = (
        settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED
        and _is_dial_candidate(execution)
    )
    if is_dial and settings.CAMPAIGN_DISPATCH_VIA_HTTP:
        _dispatch_dial_http(db, execution)
        return

    asyncio.run(run_execution(db, execution))


async def run_execution(db, execution: Execution) -> Execution:
    """Run one execution end-to-end.

    Graph-based executions (``workflow.nodes`` is non-empty) are dispatched
    to :func:`_run_graph_execution` which drives the node-handler loop.

    Legacy executions follow the existing path unchanged:
    * Dial candidates → :func:`_dial_execution` (telephony enabled).
    * All others → LLM planning stub.
    """

    from modules.campaign.workflow_model import Workflow as _Workflow

    workflow = db.get(_Workflow, execution.workflow_id)
    if workflow is not None and workflow.nodes:
        return await _run_graph_execution(db, execution, workflow)

    # --- Legacy path (unchanged) ---
    # Preferred path: place a real outbound call (Twilio AMD + voicemail drop)
    # for a campaign lead. ``_dial_execution`` owns the full outcome of the
    # attempt — success leaves the row ``running`` (reconciled later by the
    # status webhook); any failure marks the execution failed via the retry
    # engine. There is intentionally NO LLM fallback here: silently completing
    # a failed dial would hide production telephony failures.
    if settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED and _is_dial_candidate(
        execution
    ):
        await _dial_execution(db, execution)
        return execution

    execution.status = "running"
    db.commit()

    try:
        client = get_openai()

        # When the execution was enqueued for a specific lead, fold the lead +
        # playbook context into the prompt so the worker plans a real call
        # attempt. Falls back to the generic instruction for legacy flows.
        ctx = execution.context or {}
        user_payload: dict = {
            "workflow_id": str(execution.workflow_id),
            "execution_id": str(execution.id),
            "instruction": "Run campaign step.",
        }
        if ctx:
            user_payload.update(
                {
                    "campaign_id": ctx.get("campaign_id"),
                    "playbook_id": ctx.get("playbook_id"),
                    "lead": ctx.get("lead"),
                    "instruction": (
                        "Plan the next outbound call attempt for this lead "
                        "following the assigned playbook."
                    ),
                }
            )

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_EXECUTION_SYSTEM_PROMPT),
            ChatMessage(
                role=MessageRole.USER,
                content=json.dumps(user_payload),
            ),
        ]
        result = await client.complete(messages, max_tokens=256)

        execution.output = result.text or ""
        log.info(
            "campaign.execution.completed",
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            attempt=execution.attempt_number,
            tokens=result.stats.total_tokens,
        )
        # The in-process worker has no telephony outcome yet, so a successful
        # LLM plan is treated as a terminal ``completed`` outcome. When the
        # telephony layer lands it should call ``process_outcome`` with the
        # real call result (no_answer/busy/voicemail/qualified/...).
        retry_config, voicemail_config = _campaign_configs(db, execution)
        process_outcome(
            db,
            execution,
            "completed",
            retry_config=retry_config,
            voicemail_config=voicemail_config,
        )
        return execution
    except Exception as exc:  # pragma: no cover - safety net
        log.warning(
            "campaign.execution.failed",
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            attempt=execution.attempt_number,
            error=str(exc),
        )
        execution.output = f"error: {exc}"
        retry_config, voicemail_config = _campaign_configs(db, execution)
        # Infrastructure errors are transient -> let the retry engine decide
        # whether to schedule another attempt or mark the row failed/exhausted.
        process_outcome(
            db,
            execution,
            "temporary_error",
            retry_config=retry_config,
            voicemail_config=voicemail_config,
            failure_reason=str(exc),
        )
        return execution
