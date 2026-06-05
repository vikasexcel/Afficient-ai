"""HTTP API for outbound calling + Twilio webhooks.

Authenticated CRUD (``/telephony/calls/*``) sits behind the standard
role-based dependency. The webhook endpoints (``/telephony/webhooks/*``)
are public — they're authenticated by Twilio's ``X-Twilio-Signature``
header instead.
"""

from __future__ import annotations

import hmac
import uuid
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from common.logging import get_logger
from common.security.authorization import requires
from common.security.jwt import decode_token
from common.security.roles import Role
from config.settings import settings
from database.dependencies import get_db
from modules.auth.tenant import resolve_tenant
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


# Optional bearer: the initiate-call endpoint accepts EITHER a normal tenant
# JWT OR the internal service token, so we must not 401 on a missing/!bearer
# Authorization header before we've had a chance to check the internal header.
_optional_bearer = HTTPBearer(auto_error=False)

# Roles permitted to originate a call via a tenant JWT.
_INITIATE_ROLES = {Role.OWNER.value, Role.ADMIN.value, Role.AGENT.value}


def get_initiate_principal(
    request: Request,
    credentials=Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> dict:
    """Authorize ``POST /telephony/calls`` for a tenant **or** the scheduler.

    The campaign scheduler runs in the Celery worker and dispatches calls to
    this FastAPI process so the AI agent's LiveKit room + STT/LLM/TTS sessions
    live on the long-running uvicorn event loop (never a short-lived Celery
    ``asyncio.run`` loop). It authenticates with the shared internal service
    token instead of a user JWT.

    Returns either ``{"internal": True}`` (service token) or a normal tenant
    dict (``organization_id`` / ``user_id`` / ``role``).
    """

    internal = request.headers.get("X-Internal-Token")
    expected = settings.internal_service_token
    if internal and expected and hmac.compare_digest(internal, expected):
        return {"internal": True}

    # Fall back to standard tenant auth.
    if credentials is None:
        raise HTTPException(401, "Unauthorized")
    payload = decode_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(401, "Unauthorized")
    tenant = resolve_tenant(db, payload["sub"])
    if str(tenant["role"]) not in _INITIATE_ROLES:
        raise HTTPException(403, "Permission denied")
    return tenant


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
    principal=Depends(get_initiate_principal),
    svc: TelephonyService = Depends(get_telephony_service),
):
    """Originate one outbound call.

    Creates the DB row, spins up the AI agent in a LiveKit room (on this
    process's long-running event loop), then asks Twilio to dial the
    destination number. The Twilio status callbacks (``initiated`` →
    ``ringing`` → ``answered`` → ``completed``) update the same row
    asynchronously.

    Two callers:

    * Tenant (dashboard / API) — org + creator come from the JWT; the
      internal-only ``organization_id`` / ``created_by`` / ``execution_id``
      body fields are ignored.
    * Internal (campaign scheduler) — authenticated via the service token;
      org + creator + the linked campaign ``execution_id`` are taken from the
      body so the Twilio status webhook can reconcile the execution outcome.
    """

    is_internal = bool(principal.get("internal"))
    if is_internal:
        organization_id = data.organization_id
        created_by = data.created_by
        execution_id = data.execution_id
    else:
        organization_id = _tenant_org_id(principal)
        created_by = _tenant_user_id(principal)
        execution_id = None

    try:
        row = await svc.initiate_outbound(
            to_number=data.to_number,
            from_number=data.from_number,
            organization_id=organization_id,
            created_by=created_by,
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
            execution_id=execution_id,
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
# AMD / Voicemail diagnostics (admin)
# ---------------------------------------------------------------------------


@router.get("/diagnostics")
async def amd_diagnostics(
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    """Operational snapshot for the AMD / Voicemail-drop feature.

    Surfaces the runtime routing decision (Twilio path vs LiveKit-SIP path),
    the global toggles that gate real voicemail calls, and how many of the
    caller's campaigns actually have voicemail drop configured. Powers the
    "AMD Diagnostics" admin page so operators can see at a glance whether a
    real voicemail call would even run.
    """

    from modules.campaign.model import Campaign

    # Twilio client config (best-effort — never 500 the diagnostics page).
    twilio_configured = False
    twilio_dummy = (settings.TWILIO_ACCOUNT_SID or "").startswith("ACdummy")
    can_validate_sig = False
    auth_mode: str | None = None
    try:
        tw = get_twilio_client()
        twilio_configured = bool(tw.account_sid and tw.phone_number)
        can_validate_sig = tw.can_validate_signatures
        auth_mode = tw.auth_mode
    except HTTPException:
        twilio_configured = False

    public_base = (settings.TWILIO_PUBLIC_BASE_URL or "").rstrip("/")
    sip_uri = (settings.LIVEKIT_SIP_URI or "").strip()
    outbound_trunk = (settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID or "").strip()

    # The Twilio origination path is what runs AMD + posts AnsweredBy. It is
    # "active" (usable for a real voicemail call) when Twilio is really
    # configured with a public callback URL. Humans are bridged to the AI
    # agent via <Dial><Sip> which needs LIVEKIT_SIP_URI.
    twilio_path_active = bool(
        twilio_configured and not twilio_dummy and public_base
    )
    livekit_path_active = bool(outbound_trunk)

    # Org-scoped voicemail config rollup.
    org_id = _tenant_org_id(tenant)
    configured = 0
    enabled = 0
    with_recording = 0
    retry_on_vm = 0
    if org_id is not None:
        campaigns = (
            db.query(Campaign)
            .filter(Campaign.organization_id == org_id)
            .all()
        )
        for c in campaigns:
            cfg = c.voicemail_config or {}
            if cfg:
                configured += 1
            if cfg.get("voicemail_enabled"):
                enabled += 1
            if cfg.get("voicemail_message_url"):
                with_recording += 1
            if cfg.get("retry_on_voicemail"):
                retry_on_vm += 1

    # Will a *campaign* execution actually place a real AMD call today?
    # Requires the dialing flag AND the Twilio path (LiveKit-SIP has no AMD,
    # so the service forces Twilio when AMD/voicemail is requested).
    real_voicemail_call_ready = bool(
        settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED
        and settings.TWILIO_AMD_ENABLED
        and twilio_path_active
        and enabled > 0
        and with_recording > 0
    )

    blockers: list[str] = []
    if not settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED:
        blockers.append(
            "CAMPAIGN_TELEPHONY_DIALING_ENABLED is false — campaign "
            "executions will not place real Twilio calls."
        )
    if not settings.TWILIO_AMD_ENABLED:
        blockers.append("TWILIO_AMD_ENABLED is false — AMD will not run.")
    if not twilio_path_active:
        blockers.append(
            "Twilio origination path is not active (check credentials + "
            "TWILIO_PUBLIC_BASE_URL); AMD/voicemail requires it."
        )
    if not sip_uri:
        blockers.append(
            "LIVEKIT_SIP_URI is unset — humans cannot be bridged to the AI "
            "agent on AMD calls."
        )
    if enabled == 0:
        blockers.append("No campaign has voicemail drop enabled.")
    elif with_recording == 0:
        blockers.append(
            "Voicemail is enabled but no recording URL is configured."
        )

    return {
        "twilio_path_active": twilio_path_active,
        "livekit_path_active": livekit_path_active,
        "campaign_telephony_dialing_enabled": (
            settings.CAMPAIGN_TELEPHONY_DIALING_ENABLED
        ),
        "amd_enabled_global": settings.TWILIO_AMD_ENABLED,
        "amd_mode": settings.TWILIO_AMD_MODE,
        "amd_timeout_seconds": settings.TWILIO_AMD_TIMEOUT_SECONDS,
        "twilio": {
            "configured": twilio_configured,
            "dummy_credentials": twilio_dummy,
            "auth_mode": auth_mode,
            "public_base_url": public_base or None,
            "signature_validation": settings.TWILIO_VALIDATE_SIGNATURE,
            "can_validate_signatures": can_validate_sig,
            "phone_number": settings.TWILIO_PHONE_NUMBER or None,
        },
        "livekit_sip": {
            "sip_uri": sip_uri or None,
            "outbound_trunk_id": outbound_trunk or None,
        },
        "voicemail": {
            "require_public_url": settings.VOICEMAIL_REQUIRE_PUBLIC_URL,
            "url_network_check": settings.VOICEMAIL_URL_NETWORK_CHECK,
            "public_route": settings.VOICEMAIL_PUBLIC_ROUTE,
            "allowed_formats": settings.VOICEMAIL_ALLOWED_FORMATS,
            "max_bytes": settings.VOICEMAIL_MAX_BYTES,
        },
        "voicemail_config_status": {
            "campaigns_configured": configured,
            "campaigns_enabled": enabled,
            "campaigns_with_recording": with_recording,
            "campaigns_retry_on_voicemail": retry_on_vm,
        },
        "real_voicemail_call_ready": real_voicemail_call_ready,
        "blockers": blockers,
    }


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
        # Explicit, greppable marker: Twilio is about to <Play> the recording.
        log.info(
            "VOICEMAIL_PLAY_STARTED",
            call_sid=call_sid,
            room=room,
            answered_by=answered_by,
            recording_url=voicemail_url,
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
    "/webhooks/amd",
    response_model=WebhookAck,
)
async def webhook_amd(
    request: Request,
    twilio: TwilioClient = Depends(get_twilio_client),
    svc: TelephonyService = Depends(get_telephony_service),
):
    """Asynchronous AMD callback.

    Fired out-of-band after Twilio classifies the answer (``AnsweredBy``).
    The call is already bridged to the AI agent (async AMD), so when a
    machine/voicemail is detected we redirect the live leg to the voicemail
    recording here. Human answers are a no-op (the AI conversation continues).
    """

    form_dict = dict((await request.form()).multi_items())

    log.info(
        "telephony.webhook.amd.received",
        call_sid=form_dict.get("CallSid"),
        answered_by=form_dict.get("AnsweredBy"),
        machine_detection_duration=form_dict.get("MachineDetectionDuration"),
    )

    try:
        await _verify_twilio_signature(request, twilio, form_dict)
    except InvalidWebhookSignatureError as exc:
        raise _to_http(exc) from exc

    call_sid = form_dict.get("CallSid") or ""
    if call_sid:
        await svc.handle_async_amd(
            call_sid=call_sid,
            answered_by=form_dict.get("AnsweredBy"),
        )

    return WebhookAck(ok=True, call_sid=call_sid or None, status=None)


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
