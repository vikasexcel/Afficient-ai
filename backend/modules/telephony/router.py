"""HTTP API for outbound calling + Twilio webhooks.

Authenticated CRUD (``/telephony/calls/*``) sits behind the standard
role-based dependency. The webhook endpoints (``/telephony/webhooks/*``)
are public — they're authenticated by Twilio's ``X-Twilio-Signature``
header instead.
"""

from __future__ import annotations

import uuid
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from common.logging import get_logger
from common.security.authorization import requires
from common.security.roles import Role
from config.settings import settings
from database.dependencies import get_db
from modules.telephony.dependencies import (
    get_telephony_service,
    get_twilio_client,
)
from modules.telephony.exceptions import (
    CallNotFoundError,
    InvalidWebhookSignatureError,
    TelephonyError,
)
from modules.telephony.model import TelephonyCall
from modules.telephony.repository import (
    TelephonyCallRepository,
    TelephonyEventRepository,
)
from modules.telephony.schema import (
    CallEventListResponse,
    CallEventResponse,
    CallListResponse,
    CallResponse,
    InitiateCallRequest,
    RetryCallResponse,
    WebhookAck,
)
from modules.telephony.service import TelephonyService
from modules.telephony.twilio_client import TwilioClient

log = get_logger("telephony.router")

router = APIRouter(prefix="/telephony", tags=["telephony"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_http(exc: TelephonyError) -> HTTPException:
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


def _row_to_response(row: TelephonyCall) -> CallResponse:
    """SQLAlchemy → Pydantic with timezone-aware datetimes."""

    def _tz(dt):
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    return CallResponse(
        id=row.id,
        call_sid=row.call_sid,
        room_name=row.room_name,
        direction=row.direction,
        status=row.status,
        from_number=row.from_number,
        to_number=row.to_number,
        lead_id=row.lead_id,
        lead_name=row.lead_name,
        lead_phone=row.lead_phone,
        campaign_id=row.campaign_id,
        queued_at=_tz(row.queued_at),
        initiated_at=_tz(row.initiated_at),
        ringing_at=_tz(row.ringing_at),
        answered_at=_tz(row.answered_at),
        ended_at=_tz(row.ended_at),
        duration_seconds=row.duration_seconds,
        price=float(row.price) if row.price is not None else None,
        price_unit=row.price_unit,
        error_code=row.error_code,
        error_message=row.error_message,
        retry_count=row.retry_count,
        amd_result=row.amd_result,
        amd_confidence=(
            float(row.amd_confidence)
            if row.amd_confidence is not None
            else None
        ),
        voicemail_detected_at=_tz(row.voicemail_detected_at),
        voicemail_dropped=bool(row.voicemail_dropped),
        voicemail_dropped_at=_tz(row.voicemail_dropped_at),
        voicemail_recording_url=row.voicemail_recording_url,
        extra=row.extra,
        created_at=_tz(row.created_at),
        updated_at=_tz(row.updated_at),
    )


def _public_url_for(request: Request) -> str:
    """Reconstruct the Twilio-visible URL for signature validation.

    Prefer ``TWILIO_PUBLIC_BASE_URL`` because reverse proxies (ngrok,
    nginx, ALB) usually terminate TLS so ``request.url`` would otherwise
    show ``http://`` even though Twilio called us over HTTPS. Falls back
    to the raw URL when no override is configured.
    """

    base = (settings.TWILIO_PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        return str(request.url)
    # path + querystring as Twilio saw them.
    suffix = request.url.path
    if request.url.query:
        suffix = f"{suffix}?{request.url.query}"
    return f"{base}{suffix}"


async def _verify_twilio_signature(
    request: Request,
    twilio: TwilioClient,
    form: dict,
) -> None:
    if not settings.TWILIO_VALIDATE_SIGNATURE:
        return
    if not twilio.can_validate_signatures:
        # No master Auth Token configured (API-Key-only deployment).
        # Skip validation but log loudly so operators notice.
        log.warning(
            "telephony.webhook.signature_skipped",
            reason="TWILIO_AUTH_TOKEN not set",
            sid=form.get("CallSid"),
        )
        return
    signature = request.headers.get("X-Twilio-Signature")
    url = _public_url_for(request)
    if not twilio.validate_signature(
        url=url, params=form, signature=signature
    ):
        log.warning(
            "telephony.webhook.invalid_signature",
            url=url,
            sid=form.get("CallSid"),
        )
        raise InvalidWebhookSignatureError("invalid X-Twilio-Signature")


# ---------------------------------------------------------------------------
# Outbound origination
# ---------------------------------------------------------------------------


@router.post(
    "/calls", response_model=CallResponse, status_code=201
)
async def initiate_call(
    data: InitiateCallRequest,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: TelephonyService = Depends(get_telephony_service),
):
    """Originate one outbound call.

    Creates the DB row, spins up the AI agent in a LiveKit room, then
    asks Twilio to dial the destination number. The Twilio status
    callbacks (``initiated`` → ``ringing`` → ``answered`` → ``completed``)
    update the same row asynchronously.
    """

    try:
        row = await svc.initiate_outbound(
            to_number=data.to_number,
            from_number=data.from_number,
            organization_id=_tenant_org_id(tenant),
            created_by=_tenant_user_id(tenant),
            room_name=data.room_name,
            lead_id=data.lead_id,
            lead_name=data.lead_name,
            lead_phone=data.lead_phone,
            campaign_id=data.campaign_id,
            playbook_id=data.playbook_id,
            persona=data.persona,
            framework=data.qualification_framework,
            opening_line=data.opening_line,
            extra_context=data.extra_context,
            record=data.record,
            dial_timeout_seconds=data.dial_timeout_seconds,
            answering_machine_detection=data.answering_machine_detection,
            voicemail_enabled=data.voicemail_enabled,
            voicemail_message_url=data.voicemail_message_url,
            amd_unknown_fallback=data.amd_unknown_fallback,
        )
    except TelephonyError as exc:
        raise _to_http(exc) from exc
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# Listing + lookup
# ---------------------------------------------------------------------------


@router.get("/calls", response_model=CallListResponse)
async def list_calls(
    limit: int = 50,
    status: str | None = None,
    answered_by: str | None = None,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: TelephonyService = Depends(get_telephony_service),
):
    """List recent calls.

    ``answered_by`` filters by AMD classification: ``human`` | ``voicemail``
    | ``unknown`` (used by the dashboard answer-type filter).
    """

    rows = await svc.list_calls(
        organization_id=_tenant_org_id(tenant),
        limit=limit,
        status=status,
        answered_by=answered_by,
    )
    return CallListResponse(calls=[_row_to_response(r) for r in rows])


@router.get("/calls/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: uuid.UUID,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: TelephonyService = Depends(get_telephony_service),
):
    row = await svc.get_call(call_id)
    if row is None:
        raise HTTPException(404, "call not found")
    # Soft tenant scoping.
    org = _tenant_org_id(tenant)
    if row.organization_id is not None and org is not None and row.organization_id != org:
        raise HTTPException(404, "call not found")
    return _row_to_response(row)


@router.get(
    "/calls/by-sid/{call_sid}", response_model=CallResponse
)
async def get_call_by_sid(
    call_sid: str,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: TelephonyService = Depends(get_telephony_service),
):
    row = await svc.get_call_by_sid(call_sid)
    if row is None:
        raise HTTPException(404, "call not found")
    org = _tenant_org_id(tenant)
    if row.organization_id is not None and org is not None and row.organization_id != org:
        raise HTTPException(404, "call not found")
    return _row_to_response(row)


@router.get(
    "/calls/{call_id}/events", response_model=CallEventListResponse
)
async def list_call_events(
    call_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    row = TelephonyCallRepository.get(db, call_id)
    if row is None:
        raise HTTPException(404, "call not found")
    org = _tenant_org_id(tenant)
    if row.organization_id is not None and org is not None and row.organization_id != org:
        raise HTTPException(404, "call not found")

    events = TelephonyEventRepository.list_for_call(db, call_id)
    out = [
        CallEventResponse(
            id=e.id,
            call_sid=e.call_sid,
            event_type=e.event_type,
            source=e.source,
            payload=e.payload,
            created_at=(
                e.created_at
                if e.created_at.tzinfo
                else e.created_at.replace(tzinfo=timezone.utc)
            ),
        )
        for e in events
    ]
    return CallEventListResponse(events=out)


# ---------------------------------------------------------------------------
# Retry + cancel
# ---------------------------------------------------------------------------


@router.post(
    "/calls/{call_id}/retry", response_model=RetryCallResponse
)
async def retry_call(
    call_id: uuid.UUID,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: TelephonyService = Depends(get_telephony_service),
):
    try:
        new_row = await svc.retry(
            call_id=call_id,
            organization_id=_tenant_org_id(tenant),
            created_by=_tenant_user_id(tenant),
        )
    except CallNotFoundError as exc:
        raise _to_http(exc) from exc
    except TelephonyError as exc:
        raise _to_http(exc) from exc
    return RetryCallResponse(
        original_call_id=call_id,
        new_call=_row_to_response(new_row),
    )


@router.post(
    "/calls/{call_id}/cancel", response_model=CallResponse
)
async def cancel_call(
    call_id: uuid.UUID,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
    svc: TelephonyService = Depends(get_telephony_service),
):
    try:
        row = await svc.cancel(
            call_id=call_id,
            organization_id=_tenant_org_id(tenant),
        )
    except TelephonyError as exc:
        raise _to_http(exc) from exc
    return _row_to_response(row)


@router.delete("/calls/{call_id}", status_code=204)
async def delete_call(
    call_id: uuid.UUID,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: TelephonyService = Depends(get_telephony_service),
):
    """Permanently delete a call record + its event history.

    Cancels the call first if it's still live, then removes the row.
    Tenant-scoped: a call belonging to another org returns 404.
    """

    org = _tenant_org_id(tenant)
    existing = await svc.get_call(call_id)
    if existing is None:
        raise HTTPException(404, "call not found")
    if (
        existing.organization_id is not None
        and org is not None
        and existing.organization_id != org
    ):
        raise HTTPException(404, "call not found")

    try:
        await svc.delete_call(call_id=call_id, organization_id=org)
    except CallNotFoundError as exc:
        raise _to_http(exc) from exc
    except TelephonyError as exc:
        raise _to_http(exc) from exc


# ---------------------------------------------------------------------------
# Webhooks (no auth header — signed by Twilio)
# ---------------------------------------------------------------------------


@router.post(
    "/webhooks/voice",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
async def webhook_voice(
    request: Request,
    twilio: TwilioClient = Depends(get_twilio_client),
    svc: TelephonyService = Depends(get_telephony_service),
):
    """TwiML served when Twilio answers the call.

    Returns ``<Dial><Sip>...</Sip></Dial>`` that bridges the PSTN leg
    into the AI agent's LiveKit room via LiveKit's SIP gateway. The
    target room is taken from the ``room`` querystring set when we
    originated the call.
    """

    form_dict = dict((await request.form()).multi_items())

    # Full payload logging so the exact AMD fields Twilio sent are auditable.
    log.info(
        "telephony.webhook.voice.received",
        call_sid=form_dict.get("CallSid"),
        answered_by=form_dict.get("AnsweredBy"),
        call_status=form_dict.get("CallStatus"),
        machine_detection_duration=form_dict.get("MachineDetectionDuration"),
        payload=form_dict,
    )

    try:
        await _verify_twilio_signature(request, twilio, form_dict)
    except InvalidWebhookSignatureError as exc:
        raise _to_http(exc) from exc

    call_sid = form_dict.get("CallSid") or ""
    explicit_room = (
        request.query_params.get("room") or form_dict.get("room")
    )
    # Twilio synchronous AMD reports its classification as ``AnsweredBy`` on
    # the voice webhook request (after machineDetectionTimeout elapses).
    answered_by = form_dict.get("AnsweredBy")

    voicemail_url: str | None = None
    if call_sid:
        # Resolve via the service so inbound calls (no row yet) get a
        # row + AI agent runner bootstrapped on the spot.
        room, opening, voicemail_url = await svc.handle_inbound_voice(
            call_sid=call_sid,
            from_number=form_dict.get("From"),
            to_number=form_dict.get("To"),
            explicit_room=explicit_room,
            answered_by=answered_by,
        )
    else:
        # No CallSid (Twilio "validation" probe): emit safe placeholder.
        room = explicit_room or "call-probe"
        opening = None
        log.warning(
            "telephony.webhook.voice.no_call_sid",
            params=form_dict,
        )

    if voicemail_url:
        # AMD detected a machine -> play the pre-recorded voicemail instead of
        # bridging the call into the AI agent's room.
        twiml = svc.build_voicemail_twiml(recording_url=voicemail_url)
        log.info(
            "telephony.voicemail.playback.started",
            room=room,
            sid=call_sid,
            answered_by=answered_by,
            recording_url=voicemail_url,
            twiml=twiml,
        )
    else:
        twiml = svc.build_voice_twiml(room_name=room, opening_say=opening)
        log.info(
            "telephony.webhook.voice.twiml",
            room=room,
            sid=call_sid,
        )
    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/webhooks/status",
    response_model=WebhookAck,
)
async def webhook_status(
    request: Request,
    twilio: TwilioClient = Depends(get_twilio_client),
    svc: TelephonyService = Depends(get_telephony_service),
):
    """Twilio status callbacks (``initiated`` / ``ringing`` /
    ``answered`` / ``completed`` / ``failed`` / ``busy`` / ``no-answer``).

    Persists the event, applies the status transition, and (on terminal
    statuses) signals the AI agent task to wrap up.
    """

    form_dict = dict((await request.form()).multi_items())

    try:
        await _verify_twilio_signature(request, twilio, form_dict)
    except InvalidWebhookSignatureError as exc:
        raise _to_http(exc) from exc

    row = await svc.handle_status_webhook(params=form_dict)

    return WebhookAck(
        ok=True,
        call_sid=form_dict.get("CallSid"),
        status=row.status if row else None,
    )
