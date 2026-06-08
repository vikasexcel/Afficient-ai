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

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from common.logging import get_logger
from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.ai.dependencies import get_ai_service
from modules.ai.exceptions import AIError
from modules.ai.interruption import (
    InterruptionLog,
    read_metrics_snapshot,
)
from modules.ai.repository import (
    AICallRepository,
    AICallSummaryRepository,
    AITranscriptRepository,
)
from modules.playbook.exceptions import PlaybookError
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


def _to_http(exc: AIError | PlaybookError) -> HTTPException:
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
            playbook_id=data.playbook_id,
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
    except (AIError, PlaybookError) as exc:
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
    org = _tenant_org_id(tenant)

    # Strict tenant scoping: verify the call exists AND belongs to the
    # caller's organization before exposing any transcript metadata. Two
    # legitimate cases are allowed through:
    #   * The call row is owned by the caller's org.
    #   * The call row has organization_id=None (legacy / admin scripts).
    call_row = AICallRepository.get(db, call_id)
    if call_row is None:
        raise HTTPException(404, "call not found")
    if (
        call_row.organization_id is not None
        and org is not None
        and call_row.organization_id != org
    ):
        raise HTTPException(404, "call not found")

    rows = AITranscriptRepository.list_for_call(db, call_id)
    entries: list[TranscriptEntry] = []
    for r in rows:
        # Defence in depth: a stray transcript row with a different org
        # should never be served to this caller, regardless of the call
        # row scoping check above.
        if (
            r.organization_id is not None
            and org is not None
            and r.organization_id != org
        ):
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
        organization_id=(
            str(call_row.organization_id)
            if call_row.organization_id
            else None
        ),
        entries=entries,
    )


# ---------------------------------------------------------------------------
# Qualification (Redis-backed live snapshot)
# ---------------------------------------------------------------------------


def _assert_call_org(db: Session, call_id: str, org: uuid.UUID | None) -> None:
    """Raise 404 if ``call_id`` exists in the DB and belongs to a different org.

    Allows through when:
    * The call is not yet persisted (live, Redis-only call).
    * The call row has ``organization_id=None`` (legacy/admin).
    * The caller's org matches the call's org.
    """
    call_row = AICallRepository.get(db, call_id)
    if call_row is None:
        return  # live call not yet persisted — allow
    if (
        call_row.organization_id is not None
        and org is not None
        and call_row.organization_id != org
    ):
        raise HTTPException(404, "call not found")


@router.get(
    "/calls/{call_id}/qualification",
    response_model=QualificationGetResponse,
)
async def get_qualification(
    call_id: str,
    framework: str | None = None,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: AIService = Depends(get_ai_service),
):
    _assert_call_org(db, call_id, _tenant_org_id(tenant))
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
    limit: int = Query(default=50, ge=1, le=200),
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

    from modules.playbook.model import Playbook

    # Bulk-fetch summaries (1 query instead of N).
    call_ids = [r.call_id for r in rows]
    summaries = AICallSummaryRepository.map_for_call_ids(db, call_ids)

    # Bulk-fetch transcript aggregates so calls that haven't been
    # finalized yet (no summary row) still surface their saved turn
    # count / token usage / duration in the list. Without this a call
    # whose transcript rows are fully persisted would show "0 turns".
    aggregates = AITranscriptRepository.aggregate_many(db, call_ids)

    # Bulk-fetch playbooks (1 query instead of N).
    playbook_ids = {r.playbook_id for r in rows if r.playbook_id}
    playbook_names: dict = {}
    if playbook_ids:
        for pb in (
            db.query(Playbook)
            .filter(Playbook.id.in_(list(playbook_ids)))
            .all()
        ):
            playbook_names[pb.id] = pb.name

    entries: list[CallListEntry] = []
    for r in rows:
        summary = summaries.get(r.call_id)
        agg = aggregates.get(r.call_id, {})
        playbook_name = (
            playbook_names.get(r.playbook_id) if r.playbook_id else None
        )

        # Prefer the finalized summary row; otherwise fall back to the
        # live transcript aggregate so saved turns are never hidden.
        total_turns = (
            summary.total_turns if summary else int(agg.get("total_turns") or 0)
        )
        total_tokens = (
            summary.total_tokens if summary else int(agg.get("total_tokens") or 0)
        )
        duration_ms = (
            summary.duration_ms
            if summary and summary.duration_ms is not None
            else agg.get("duration_ms")
        )

        entries.append(
            CallListEntry(
                call_id=r.call_id,
                persona=r.persona,
                framework=r.framework,
                playbook_id=str(r.playbook_id) if r.playbook_id else None,
                playbook_name=playbook_name,
                playbook_version=r.playbook_version,
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
                total_turns=total_turns,
                total_tokens=total_tokens,
                duration_ms=duration_ms,
            )
        )
    return CallListResponse(calls=entries)


# ---------------------------------------------------------------------------
# Personas (read-only listing)
# ---------------------------------------------------------------------------


@router.get("/calls/{call_id}/interruptions")
async def list_interruptions(
    call_id: str,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: AIService = Depends(get_ai_service),
):
    """Return the in-call barge-in event log + live metrics snapshot.

    Sourced from Redis (the orchestrator writes both lists during the
    call). After ``finalize_call`` clears memory these reads will return
    empty; in the future we can mirror events to Postgres if long-term
    history is required.
    """

    _assert_call_org(db, call_id, _tenant_org_id(tenant))
    log_store = InterruptionLog(svc.memory)
    try:
        events = await log_store.list_for_call(call_id)
        snapshot = await read_metrics_snapshot(svc.memory, call_id=call_id)
    except AIError as exc:
        raise _to_http(exc) from exc

    return {
        "call_id": call_id,
        "metrics": snapshot,
        "events": [e.to_dict() for e in events],
    }


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
