"""CALL node handler.

Wraps the existing telephony and LLM-stub execution logic from
:mod:`modules.campaign.worker`.  No telephony code is rewritten here —
worker functions are imported lazily to avoid circular imports and reused
verbatim.

Execution paths
---------------
Telephony enabled + dial candidate
    Delegates to :func:`~modules.campaign.worker._dial_execution` (async).
    The execution is left ``running``; the Twilio status webhook reconciles
    the final outcome asynchronously.  Returns ``advance=False``.

Non-telephony (LLM planning stub)
    Runs the existing OpenAI planning step, sets the execution ``running``
    during the call, and returns ``advance=True`` so the graph executor
    immediately moves to the next node.
    ``process_outcome`` is intentionally NOT called — the graph framework
    (STOP node or future Condition node) decides when the execution is
    terminal.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from common.logging import get_logger
from modules.campaign.node_handlers.base import BaseNodeHandler, NodeResult

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from modules.campaign.execution_model import Execution

log = get_logger("campaign.node_handlers.call")


class CallNodeHandler(BaseNodeHandler):
    """Execute a CALL node by placing (or planning) an outbound call."""

    async def execute(
        self,
        db: "Session",
        execution: "Execution",
        node: dict,
    ) -> NodeResult:
        # Lazy imports break the worker ↔ node_handlers circular dependency.
        from config.settings import settings
        from modules.campaign.worker import (
            _EXECUTION_SYSTEM_PROMPT,
            _campaign_configs,
            _dial_execution,
            _is_dial_candidate,
        )

        # ------------------------------------------------------------------ #
        # Telephony path — place a real outbound call.
        # Mirrors the logic in worker.run_execution but without falling back
        # to the LLM stub on telephony availability failures.
        # ------------------------------------------------------------------ #
        if (
            settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED
            and _is_dial_candidate(execution)
        ):
            await _dial_execution(db, execution)

            if execution.status == "running":
                # Dial placed; Twilio webhook will reconcile the final outcome.
                return NodeResult(
                    outcome="running",
                    advance=False,
                    output={"outcome": "running"},
                )

            # Dial failed — _fail_dial / process_outcome already handled it.
            return NodeResult(
                outcome="failed",
                advance=False,
                output={
                    "outcome": "failed",
                    "error": execution.last_failure_reason or "dial failed",
                },
            )

        # ------------------------------------------------------------------ #
        # LLM planning stub — used when telephony is disabled (dev / test).
        # Sets execution to "running" while the LLM call is in flight;
        # does NOT call process_outcome so the graph framework controls
        # when the execution is marked terminal.
        # ------------------------------------------------------------------ #
        from modules.ai.dependencies import get_openai
        from modules.ai.schema import ChatMessage, MessageRole

        execution.status = "running"
        db.commit()

        try:
            client = get_openai()

            ctx = execution.context or {}
            user_payload: dict = {
                "workflow_id": str(execution.workflow_id),
                "execution_id": str(execution.id),
                "instruction": "Run campaign CALL step.",
            }
            if ctx:
                user_payload.update(
                    {
                        "campaign_id": ctx.get("campaign_id"),
                        "playbook_id": ctx.get("playbook_id"),
                        "lead": ctx.get("lead"),
                        "instruction": (
                            "Plan the next outbound call attempt for this "
                            "lead following the assigned playbook."
                        ),
                    }
                )

            messages = [
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=_EXECUTION_SYSTEM_PROMPT,
                ),
                ChatMessage(
                    role=MessageRole.USER,
                    content=json.dumps(user_payload),
                ),
            ]
            result = await client.complete(messages, max_tokens=256)
            plan_text = result.text or ""

            log.info(
                "campaign.node.call.planned",
                execution_id=str(execution.id),
                node_id=node.get("id"),
                tokens=result.stats.total_tokens,
            )

            # Leave execution "running"; graph executor advances to next node.
            return NodeResult(
                outcome="completed",
                advance=True,
                output={"outcome": "completed", "plan": plan_text},
            )

        except Exception as exc:
            log.warning(
                "campaign.node.call.failed",
                execution_id=str(execution.id),
                node_id=node.get("id"),
                error=str(exc),
            )
            execution.status = "failed"
            execution.last_failure_reason = str(exc)
            db.flush()
            return NodeResult(
                outcome="failed",
                advance=False,
                output={"outcome": "failed", "error": str(exc)},
            )
