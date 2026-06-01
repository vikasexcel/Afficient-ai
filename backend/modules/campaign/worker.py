"""In-process execution worker.

Runs one campaign-execution synchronously from the request handler. The
worker exists so the same code path can later be moved to Celery (already
in ``requirements.txt``) without changing callers.

This module replaces the legacy ``AIService.execute`` shim (which was
removed during the GPT-4o refactor) with a direct call into the modern
:class:`~modules.ai.openai_client.OpenAIClient`.
"""

from __future__ import annotations

import json

from common.logging import get_logger
from modules.ai.dependencies import get_openai
from modules.ai.schema import ChatMessage, MessageRole
from modules.campaign.execution_model import Execution

log = get_logger("campaign.worker")


_EXECUTION_SYSTEM_PROMPT = (
    "You are the campaign execution worker for Aifficient. Given the "
    "workflow context below, output a short JSON object summarising "
    "what the next call attempt should do. Always return valid JSON."
)


async def run_execution(db, execution: Execution) -> Execution:
    """Run one execution end-to-end.

    Marks the row ``running``, calls the LLM with a short structured
    prompt, captures the text output, and marks the row ``completed`` (or
    ``failed`` if anything raised).
    """

    execution.status = "running"
    db.commit()

    try:
        client = get_openai()
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_EXECUTION_SYSTEM_PROMPT),
            ChatMessage(
                role=MessageRole.USER,
                content=json.dumps(
                    {
                        "workflow_id": str(execution.workflow_id),
                        "execution_id": str(execution.id),
                        "instruction": "Run campaign step.",
                    }
                ),
            ),
        ]
        result = await client.complete(messages, max_tokens=256)

        execution.output = result.text or ""
        execution.status = "completed"
        log.info(
            "campaign.execution.completed",
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            tokens=result.stats.total_tokens,
        )
    except Exception as exc:  # pragma: no cover - safety net
        log.warning(
            "campaign.execution.failed",
            execution_id=str(execution.id),
            workflow_id=str(execution.workflow_id),
            error=str(exc),
        )
        execution.status = "failed"
        execution.output = f"error: {exc}"

    db.commit()
    db.refresh(execution)
    return execution
