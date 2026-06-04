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
import uuid

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


def _campaign_dial_context(db, execution: Execution) -> dict | None:
    """Resolve everything needed to place a real outbound call for a lead.

    Returns ``None`` when the execution can't be dialled (no lead phone, no
    playbook, or no owning campaign/org), so the caller falls back to the
    legacy LLM-plan path.
    """

    from modules.campaign.model import Campaign
    from modules.campaign.workflow_model import Workflow

    ctx = execution.context or {}
    lead = ctx.get("lead") or {}
    phone = (lead.get("phone") or "").strip()
    if not phone:
        return None

    workflow = db.get(Workflow, execution.workflow_id)
    if workflow is None:
        return None
    campaign = db.get(Campaign, workflow.campaign_id)
    if campaign is None or not campaign.playbook_id:
        return None

    return {
        "to_number": phone,
        "organization_id": campaign.organization_id,
        "created_by": campaign.created_by,
        "campaign_id": campaign.id,
        "playbook_id": campaign.playbook_id,
        "lead_id": (
            uuid.UUID(lead["id"]) if lead.get("id") else None
        ),
        "lead_name": lead.get("name"),
        "lead_phone": phone,
    }


async def _dial_execution(db, execution: Execution) -> bool:
    """Place a real outbound telephony call for this execution.

    Returns ``True`` when a call was originated (the execution is left
    ``running`` and its outcome is reconciled later by the Twilio status
    webhook via ``TelephonyService._reconcile_campaign_execution``). Returns
    ``False`` when dialling isn't possible so the caller falls back to the LLM
    plan path.
    """

    dial = _campaign_dial_context(db, execution)
    if dial is None:
        log.info(
            "campaign.execution.dial_skipped",
            execution_id=str(execution.id),
            reason="missing lead phone / playbook / campaign",
        )
        return False

    try:
        from modules.telephony.dependencies import get_telephony_service

        svc = get_telephony_service()
    except Exception as exc:  # telephony not configured -> fall back
        log.warning(
            "campaign.execution.telephony_unavailable",
            execution_id=str(execution.id),
            error=str(exc),
        )
        return False

    execution.status = "running"
    db.commit()

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
    return True


async def run_execution(db, execution: Execution) -> Execution:
    """Run one execution end-to-end.

    Marks the row ``running``, calls the LLM with a short structured
    prompt, captures the text output, and marks the row ``completed`` (or
    ``failed`` if anything raised).
    """

    # Preferred path: place a real outbound call (Twilio AMD + voicemail drop).
    # The terminal outcome is reconciled later by the status webhook, so we
    # return here with the execution left ``running``.
    if settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED:
        try:
            if await _dial_execution(db, execution):
                return execution
        except Exception as exc:  # dialling failed -> fall back to LLM plan
            log.warning(
                "campaign.execution.dial_failed",
                execution_id=str(execution.id),
                error=str(exc),
            )

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
