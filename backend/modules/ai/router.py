"""HTTP API for the AI conversation engine.

Five endpoints:

* ``POST /api/v1/ai/generate``       — stateless one-shot completion.
* ``POST /api/v1/ai/converse``       — single stateful turn within a call.
* ``GET  /api/v1/ai/calls/{id}/transcript``
* ``GET  /api/v1/ai/calls/{id}/qualification``
* ``POST /api/v1/ai/calls/{id}/finalize`` — generate summary + persist.

The live conversation loop is **not** an HTTP endpoint; it runs inside
:class:`modules.ai.orchestrator.ConversationOrchestrator` and is started
by a worker (e.g. the LiveKit room webhook in a future phase).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from common.logging import get_logger
from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.ai.dependencies import get_ai_service
from modules.ai.exceptions import AIError
from modules.ai.repository import (
    AICallRepository,
    AICallSummaryRepository,
    AITranscriptRepository,
)
from modules.ai.schema import (
    CallListEntry,
    CallListResponse,
    CallSummaryResponse,
    ChatMessage,
    ConverseRequest,
    ConverseResponse,
    GenerateRequest,
    GenerateResponse,
    MessageRole,
    QualificationGetResponse,
    QualificationSnapshot,
    TranscriptEntry,
    TranscriptResponse,
)
from modules.ai.service import AIService

log = get_logger("ai.router")

router = APIRouter(prefix="/ai", tags=["ai"])


def _to_http(exc: AIError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _tenant_org_id(tenant: dict) -> uuid.UUID | None:
    org = tenant.get("organization_id")
    if not org:
        return None
    try:
        return uuid.UUID(str(org))
    except (TypeError, ValueError):
        return None


def _tenant_user_id(tenant: dict) -> uuid.UUID | None:
    sub = tenant.get("user_id")
    if not sub:
        return None
    try:
        return uuid.UUID(str(sub))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Stateless generate
# ---------------------------------------------------------------------------


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    data: GenerateRequest,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: AIService = Depends(get_ai_service),
):
    messages: list[ChatMessage] = []
    if data.system:
        messages.append(ChatMessage(role=MessageRole.SYSTEM, content=data.system))
    messages.append(ChatMessage(role=MessageRole.USER, content=data.prompt))

    try:
        result = await svc.openai.complete(
            messages,
            model=data.model,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            user=str(tenant.get("user_id")) if tenant.get("user_id") else None,
        )
    except AIError as exc:
        raise _to_http(exc) from exc

    return GenerateResponse(
        output=result.text,
        model=result.stats.model,
        finish_reason=result.stats.finish_reason,
        prompt_tokens=result.stats.prompt_tokens,
        completion_tokens=result.stats.completion_tokens,
        total_tokens=result.stats.total_tokens,
        latency_ms=result.stats.latency_ms,
    )


# ---------------------------------------------------------------------------
# Stateful converse (one turn)
# ---------------------------------------------------------------------------


@router.post("/converse", response_model=ConverseResponse)
async def converse(
    data: ConverseRequest,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: AIService = Depends(get_ai_service),
):
    org_id = _tenant_org_id(tenant)
    user_id = _tenant_user_id(tenant)

    # Idempotent: if this is the first turn for the call_id, start_call
    # writes the AI call row + Redis meta. Subsequent turns find the
    # existing row and update persona/framework only if provided.
    try:
        await svc.start_call(
            call_id=data.call_id,
            persona=data.persona,
            framework=data.qualification_framework,
            organization_id=org_id,
            created_by=user_id,
            extra_context=data.extra_context,
        )
        result = await svc.respond_turn(
            call_id=data.call_id,
            user_input=data.user_input,
            persona=data.persona,
            framework=data.qualification_framework,
            extra_context=data.extra_context,
            organization_id=org_id,
            persist_transcript=data.persist_transcript,
        )
    except AIError as exc:
        raise _to_http(exc) from exc

    return ConverseResponse(
        call_id=data.call_id,
        reply=result.reply,
        model=result.stats.model,
        finish_reason=result.stats.finish_reason,
        prompt_tokens=result.stats.prompt_tokens,
        completion_tokens=result.stats.completion_tokens,
        total_tokens=result.stats.total_tokens,
        latency_ms=result.stats.latency_ms,
        history_length=result.history_length,
        qualification=result.qualification,
    )


# ---------------------------------------------------------------------------
# Transcript (DB-backed)
# ---------------------------------------------------------------------------


@router.get(
    "/calls/{call_id}/transcript", response_model=TranscriptResponse
)
async def get_transcript(
    call_id: str,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    rows = AITranscriptRepository.list_for_call(db, call_id)
    org = _tenant_org_id(tenant)
    entries: list[TranscriptEntry] = []
    for r in rows:
        # Soft tenant scoping: if the row was written for a specific org,
        # only return it to the same org. Rows with org=None are global
        # (admin scripts / e2e tests) and visible to anyone with the role.
        if r.organization_id is not None and org is not None and r.organization_id != org:
            continue
        try:
            role = MessageRole(r.role)
        except ValueError:
            continue
        entries.append(
            TranscriptEntry(
                role=role,
                content=r.content,
                ts=r.created_at.replace(tzinfo=timezone.utc)
                if r.created_at.tzinfo is None
                else r.created_at,
                latency_ms=r.latency_ms,
                prompt_tokens=r.prompt_tokens,
                completion_tokens=r.completion_tokens,
            )
        )

    return TranscriptResponse(
        call_id=call_id,
        organization_id=str(org) if org else None,
        entries=entries,
    )


# ---------------------------------------------------------------------------
# Qualification (Redis-backed live snapshot)
# ---------------------------------------------------------------------------


@router.get(
    "/calls/{call_id}/qualification",
    response_model=QualificationGetResponse,
)
async def get_qualification(
    call_id: str,
    framework: str | None = None,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: AIService = Depends(get_ai_service),
):
    try:
        snapshot: QualificationSnapshot = await svc.get_qualification(
            call_id, framework=framework
        )
    except AIError as exc:
        raise _to_http(exc) from exc
    return QualificationGetResponse(call_id=call_id, qualification=snapshot)


# ---------------------------------------------------------------------------
# Finalize call (summary + DB write)
# ---------------------------------------------------------------------------


@router.post(
    "/calls/{call_id}/finalize", response_model=CallSummaryResponse
)
async def finalize_call(
    call_id: str,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: AIService = Depends(get_ai_service),
):
    org_id = _tenant_org_id(tenant)
    try:
        await svc.finalize_call(call_id=call_id, organization_id=org_id)
    except AIError as exc:
        raise _to_http(exc) from exc

    row = AICallSummaryRepository.get(db, call_id)
    if row is None:
        raise HTTPException(404, "call summary not found")

    qual_payload: QualificationSnapshot | None = None
    if row.qualification:
        try:
            qual_payload = QualificationSnapshot.model_validate(row.qualification)
        except Exception:
            qual_payload = None

    return CallSummaryResponse(
        call_id=row.call_id,
        summary=row.summary,
        qualification=qual_payload,
        total_turns=row.total_turns,
        total_tokens=row.total_tokens,
        duration_ms=row.duration_ms,
        created_at=row.created_at.replace(tzinfo=timezone.utc)
        if row.created_at.tzinfo is None
        else row.created_at,
        updated_at=row.updated_at.replace(tzinfo=timezone.utc)
        if row.updated_at.tzinfo is None
        else row.updated_at,
    )


# ---------------------------------------------------------------------------
# Calls listing (for Transcripts page)
# ---------------------------------------------------------------------------


@router.get("/calls", response_model=CallListResponse)
async def list_calls(
    limit: int = 50,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    """List recent AI calls scoped to the caller's organization.

    Joins each call with its summary row (if any) so the frontend can
    render a list view with qualification + summary previews in a single
    round-trip.
    """

    org = _tenant_org_id(tenant)
    rows = AICallRepository.list_recent(db, organization_id=org, limit=limit)

    entries: list[CallListEntry] = []
    for r in rows:
        summary = AICallSummaryRepository.get(db, r.call_id)
        entries.append(
            CallListEntry(
                call_id=r.call_id,
                persona=r.persona,
                framework=r.framework,
                status=r.status,
                created_at=r.created_at.replace(tzinfo=timezone.utc)
                if r.created_at.tzinfo is None
                else r.created_at,
                updated_at=r.updated_at.replace(tzinfo=timezone.utc)
                if r.updated_at.tzinfo is None
                else r.updated_at,
                summary=summary.summary if summary else None,
                qualification_status=summary.qualification_status if summary else None,
                qualification_score=summary.qualification_score if summary else None,
                total_turns=summary.total_turns if summary else 0,
                total_tokens=summary.total_tokens if summary else 0,
            )
        )
    return CallListResponse(calls=entries)


# ---------------------------------------------------------------------------
# Personas (read-only listing)
# ---------------------------------------------------------------------------


@router.get("/personas")
async def list_personas_endpoint(
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    from modules.ai.prompts import list_personas

    return {
        "personas": [
            {
                "name": p.name,
                "description": p.description,
                "default_objective": p.default_objective,
            }
            for p in list_personas()
        ]
    }
