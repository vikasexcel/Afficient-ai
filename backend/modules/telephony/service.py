"""High-level telephony service.

Glues the Twilio REST client, LiveKit room control, the AI conversation
orchestrator, and the ``telephony_calls`` / ``telephony_events`` tables
into one cohesive API.

Public surface used by the router:

* :meth:`TelephonyService.initiate_outbound` — create row + room +
  background AI agent, then originate the Twilio call.
* :meth:`TelephonyService.handle_status_webhook` — apply Twilio's status
  callback to the row and bookkeep the event log.
* :meth:`TelephonyService.build_voice_twiml` — TwiML for the
  ``/webhooks/voice`` endpoint.
* :meth:`TelephonyService.retry` — re-dial a failed call (new SID,
  same room reused so the agent state continues).
* :meth:`TelephonyService.cancel` — abort an in-flight call.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

from sqlalchemy.orm import Session

from common.logging import get_logger
from config.settings import settings
from database.session import SessionLocal
from modules.livekit.exceptions import LiveKitError
from modules.livekit.schema import CreateRoomRequest
from modules.livekit.service import LiveKitService
from modules.telephony.agent_runner import (
    CallAgentRegistry,
    CallAgentRunner,
)
from modules.telephony.exceptions import (
    CallNotFoundError,
    TelephonyError,
    TwilioProviderError,
)
from modules.telephony.model import (
    CALL_STATUS_CANCELED,
    CALL_STATUS_COMPLETED,
    CALL_STATUS_FAILED,
    CALL_STATUS_INITIATED,
    CALL_STATUS_QUEUED,
    TERMINAL_STATUSES,
    TelephonyCall,
)
from modules.telephony.repository import (
    TelephonyCallRepository,
    TelephonyEventRepository,
)
from modules.livekit.model import LiveKitSession
from modules.livekit.repository import LiveKitSessionRepository
from modules.telephony.twilio_client import TwilioClient

log = get_logger("telephony.service")


@contextmanager
def _db_scope() -> Iterator[Session]:
    """Local DB session (matches the AI service pattern)."""

    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _detach_call(db: Session, row: TelephonyCall | None) -> TelephonyCall | None:
    """Expunge a row so it stays usable after the session closes.

    ``initiate_outbound`` and friends run DB work in ``asyncio.to_thread``;
    without this, accessing ``row.id`` after the thread returns raises
    ``DetachedInstanceError``.
    """

    if row is None:
        return None
    db.refresh(row)
    db.expunge(row)
    return row


def _detach_calls(
    db: Session, rows: Sequence[TelephonyCall]
) -> list[TelephonyCall]:
    out: list[TelephonyCall] = []
    for row in rows:
        db.refresh(row)
        db.expunge(row)
        out.append(row)
    return out


# Twilio status → our canonical status. Twilio uses the exact strings
# below as the ``CallStatus`` field on status callbacks; we keep them
# 1:1 so the column is greppable against Twilio logs.
_TWILIO_STATUS_MAP = {
    "queued": CALL_STATUS_QUEUED,
    "initiated": CALL_STATUS_INITIATED,
    "ringing": "ringing",
    "in-progress": "in-progress",
    "answered": "in-progress",
    "completed": CALL_STATUS_COMPLETED,
    "failed": CALL_STATUS_FAILED,
    "busy": "busy",
    "no-answer": "no-answer",
    "canceled": CALL_STATUS_CANCELED,
}


class TelephonyService:
    """Composes Twilio + LiveKit + AI orchestrator + persistence."""

    def __init__(
        self,
        *,
        twilio: TwilioClient,
        livekit: LiveKitService,
        agent_registry: CallAgentRegistry,
    ) -> None:
        self._twilio = twilio
        self._livekit = livekit
        self._registry = agent_registry

    # ------------------------------------------------------------------
    # Outbound origination
    # ------------------------------------------------------------------

    async def initiate_outbound(
        self,
        *,
        to_number: str,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
        from_number: str | None = None,
        room_name: str | None = None,
        lead_id: uuid.UUID | None = None,
        lead_name: str | None = None,
        lead_phone: str | None = None,
        campaign_id: uuid.UUID | None = None,
        playbook_id: uuid.UUID | None = None,
        persona: str | None = None,
        framework: str | None = None,
        opening_line: str | None = None,
        extra_context: dict[str, Any] | None = None,
        record: bool | None = None,
        dial_timeout_seconds: int | None = None,
        answering_machine_detection: bool = False,
        parent_call_id: uuid.UUID | None = None,
        retry_count: int = 0,
    ) -> TelephonyCall:
        """Full outbound flow.

        Order matters here:

        1. Generate a deterministic ``room_name`` and insert the DB row
           so we have something to roll back against.
        2. Create the LiveKit room and spawn the AI agent so it's
           sitting in the room before the PSTN leg lands.
        3. Originate the Twilio call — its TwiML callback will bridge
           the carrier audio into the same room over SIP.
        4. Patch the row with the returned ``CallSid``.

        If any later step fails we mark the row as ``failed`` and stop
        the agent task so we don't leak a background coroutine.
        """

        effective_from = from_number or self._twilio.phone_number
        effective_room = (
            room_name or self._generate_room_name(organization_id)
        )
        effective_persona = persona or settings.AI_DEFAULT_PERSONA
        effective_framework = framework or settings.AI_QUALIFICATION_FRAMEWORK
        effective_opening = opening_line
        effective_playbook_id = playbook_id
        effective_voice_id: str | None = None
        effective_voice_name: str | None = None
        effective_voice_provider: str | None = None
        playbook_runtime = None

        if playbook_id:
            if not organization_id:
                raise TelephonyError(
                    "A playbook requires an organization context to load",
                    status_code=400,
                )

            log.info(
                "telephony.PLAYBOOK_SELECTED",
                playbook_id=str(playbook_id),
            )

            from modules.playbook.exceptions import PlaybookError
            from modules.playbook.call_apply import (
                build_call_extra_context,
                playbook_application_summary,
            )
            from modules.playbook.company import (
                resolve_agent_name,
                resolve_opening_line,
            )

            try:
                playbook_runtime = await asyncio.to_thread(
                    self._load_playbook,
                    organization_id=organization_id,
                    playbook_id=playbook_id,
                )
            except PlaybookError as exc:
                raise TelephonyError(exc.message, status_code=exc.status_code) from exc

            summary = playbook_application_summary(playbook_runtime)
            agent_name = resolve_agent_name(playbook_runtime)
            log.info(
                "telephony.PLAYBOOK_LOADED",
                **summary,
                organization_id=str(organization_id),
            )
            log.info(
                "telephony.AGENT_NAME_LOADED",
                playbook_id=str(playbook_runtime.playbook_id),
                agent_name=agent_name,
            )

            # Playbook is the single source of truth for conversation config.
            effective_persona = playbook_runtime.persona_name
            effective_framework = playbook_runtime.framework
            effective_playbook_id = playbook_runtime.playbook_id
            effective_voice_id = playbook_runtime.voice_id
            effective_voice_name = playbook_runtime.voice_name
            effective_voice_provider = playbook_runtime.voice_provider

            extra_context = build_call_extra_context(
                playbook_runtime,
                lead_name=lead_name,
                lead_phone=lead_phone or to_number,
                caller_extra=extra_context,
                playbook_controls_call=True,
            )
            effective_opening = resolve_opening_line(
                playbook_runtime,
                agent_name=agent_name,
            )

            log.info(
                "telephony.PLAYBOOK_APPLIED",
                room=effective_room,
                **summary,
            )
            log.info(
                "telephony.AGENT_NAME_APPLIED",
                playbook_id=str(effective_playbook_id),
                agent_name=agent_name,
                opening_line=effective_opening,
            )
            resolved_voice = (
                effective_voice_id or settings.ELEVENLABS_VOICE_ID or None
            )
            log.info(
                "telephony.VOICE_APPLIED",
                playbook_id=str(effective_playbook_id),
                playbook_name=summary["playbook_name"],
                voice_id=resolved_voice,
                voice_name=effective_voice_name,
                provider=effective_voice_provider or "elevenlabs",
                source="playbook" if effective_voice_id else "env_default",
            )
        elif extra_context is None:
            extra_context = {}

        # 1. DB row first so we always have an audit trail.
        row = await asyncio.to_thread(
            self._insert_call_row,
            organization_id=organization_id,
            created_by=created_by,
            room_name=effective_room,
            from_number=effective_from,
            to_number=to_number,
            lead_id=lead_id,
            lead_name=lead_name,
            lead_phone=lead_phone,
            campaign_id=campaign_id,
            persona=effective_persona,
            framework=effective_framework,
            opening_line=effective_opening,
            extra_context=extra_context,
            parent_call_id=parent_call_id,
            retry_count=retry_count,
            playbook_id=effective_playbook_id,
        )

        log.info(
            "telephony.initiate.row_created",
            call_id=str(row.id),
            room=effective_room,
            to=to_number,
            from_=effective_from,
            org=str(organization_id) if organization_id else None,
        )

        # 2. Ensure the LiveKit room + local session row exist before the
        #    agent runner and Twilio leg race to connect.
        try:
            room_resp = await self.ensure_room(effective_room)
            await asyncio.to_thread(
                self._upsert_livekit_session,
                room_name=effective_room,
                organization_id=organization_id,
                created_by=created_by,
                livekit_sid=getattr(room_resp, "sid", None)
                if room_resp is not None
                else None,
            )
        except LiveKitError as exc:
            log.warning(
                "telephony.initiate.livekit_room_failed",
                room=effective_room,
                error=exc.message,
            )

        # 3. Spawn the AI agent runner so it's in the room when
        #    the PSTN audio arrives. Idempotent.
        runner = CallAgentRunner(
            room_name=effective_room,
            call_id=effective_room,
            organization_id=organization_id,
            created_by=created_by,
            persona=effective_persona,
            framework=effective_framework,
            playbook_id=effective_playbook_id,
            opening_line=effective_opening,
            voice_id=effective_voice_id,
            voice_name=effective_voice_name,
            voice_provider=effective_voice_provider,
            extra_context=self._build_agent_context(
                lead_name=lead_name,
                lead_phone=lead_phone or to_number,
                extra=extra_context,
            ),
        )
        await self._registry.register(runner)
        if effective_playbook_id and playbook_runtime is not None:
            log.info(
                "telephony.CALL_STARTED_WITH_PLAYBOOK",
                room=effective_room,
                call_id=str(row.id),
                playbook_id=str(effective_playbook_id),
                playbook_name=playbook_runtime.name,
                persona=effective_persona,
                framework=effective_framework,
                voice_id=effective_voice_id or settings.ELEVENLABS_VOICE_ID or None,
            )
        await self._record_event(
            event_type="ai_agent_started",
            telephony_call_id=row.id,
            organization_id=organization_id,
            source="internal",
            payload={
                "room": effective_room,
                "playbook_id": str(effective_playbook_id)
                if effective_playbook_id
                else None,
            },
        )

        # 4. Originate. Preferred path: LiveKit dials the lead directly
        #    into the agent's room over the outbound SIP trunk. Falls back
        #    to Twilio TwiML <Dial><Sip> when no outbound trunk is set.
        if settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID:
            row = await asyncio.to_thread(
                self._apply_status_update,
                telephony_call_id=row.id,
                status=CALL_STATUS_INITIATED,
                initiated_at=datetime.utcnow(),
                duration_seconds=None,
                error_code=None,
                error_message=None,
                extra_merge={"dial_mode": "livekit_sip"},
            )
            asyncio.create_task(
                self._run_livekit_sip_call(
                    telephony_call_id=row.id,
                    room_name=effective_room,
                    to_number=to_number,
                    organization_id=organization_id,
                ),
                name=f"lk-sip-dial:{effective_room}",
            )
            log.info(
                "telephony.initiate.done",
                call_id=str(row.id),
                room=effective_room,
                dial_mode="livekit_sip",
            )
            return row

        # 4b. Originate via Twilio.
        try:
            originated = await self._twilio.create_call(
                to_number=to_number,
                from_number=effective_from,
                room_name=effective_room,
                dial_timeout_seconds=dial_timeout_seconds,
                record=record,
                answering_machine_detection=answering_machine_detection,
            )
        except TelephonyError as exc:
            await self._mark_failed(
                row.id,
                organization_id=organization_id,
                error_code="twilio_originate_failed",
                error_message=exc.message,
            )
            await self._registry.stop(effective_room, wait=False)
            raise

        # 5. Persist the SID + initial status.
        row = await asyncio.to_thread(
            self._set_sid,
            telephony_call_id=row.id,
            call_sid=originated.sid,
            status=_TWILIO_STATUS_MAP.get(
                (originated.status or "").lower(),
                CALL_STATUS_INITIATED,
            ),
        )
        await self._record_event(
            event_type="originated",
            call_sid=originated.sid,
            telephony_call_id=row.id,
            organization_id=organization_id,
            source="internal",
            payload={
                "twilio_status": originated.status,
                "to": originated.to,
                "from": originated.from_,
            },
        )

        log.info(
            "telephony.initiate.done",
            call_id=str(row.id),
            call_sid=originated.sid,
            twilio_status=originated.status,
            room=effective_room,
        )
        return row

    # ------------------------------------------------------------------
    # LiveKit-originated SIP call lifecycle (background task)
    # ------------------------------------------------------------------

    async def _run_livekit_sip_call(
        self,
        *,
        telephony_call_id: uuid.UUID,
        room_name: str,
        to_number: str,
        organization_id: uuid.UUID | None,
    ) -> None:
        """Dial the lead over LiveKit SIP and drive the row's lifecycle.

        Runs detached from the HTTP request:

        1. ``CreateSIPParticipant`` (blocks until answered / failed).
        2. On answer → mark ``in-progress``; on failure → map the SIP
           status to failed / busy / no-answer and stop the agent.
        3. Poll the room until the caller's SIP participant leaves (hangup)
           or the agent task ends, then mark ``completed``.
        """

        result = await self._livekit.create_sip_participant(
            room_name=room_name,
            to_number=to_number,
            trunk_id=settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID,
            identity="sip-caller",
        )

        if not result.answered:
            status, code = _sip_status_to_call_status(result.sip_status_code)
            await asyncio.to_thread(
                self._apply_status_update,
                telephony_call_id=telephony_call_id,
                status=status,
                ended_at=datetime.utcnow(),
                error_code=code,
                error_message=result.error,
                extra_merge={"dial_mode": "livekit_sip"},
            )
            await self._record_event(
                event_type=status,
                telephony_call_id=telephony_call_id,
                organization_id=organization_id,
                source="livekit",
                payload={
                    "sip_status_code": result.sip_status_code,
                    "error": result.error,
                },
            )
            await self._registry.stop(room_name, wait=False)
            log.info(
                "telephony.livekit_sip.not_answered",
                call_id=str(telephony_call_id),
                room=room_name,
                status=status,
                sip_status=result.sip_status_code,
            )
            return

        answered_at = datetime.utcnow()
        await asyncio.to_thread(
            self._apply_status_update,
            telephony_call_id=telephony_call_id,
            status="in-progress",
            answered_at=answered_at,
            extra_merge={
                "dial_mode": "livekit_sip",
                "sip_call_id": result.sip_call_id,
            },
        )
        if result.sip_call_id:
            await asyncio.to_thread(
                self._set_sid,
                telephony_call_id=telephony_call_id,
                call_sid=result.sip_call_id,
                status="in-progress",
            )
        await self._record_event(
            event_type="answered",
            call_sid=result.sip_call_id,
            telephony_call_id=telephony_call_id,
            organization_id=organization_id,
            source="livekit",
            payload={"identity": result.identity},
        )
        log.info(
            "telephony.livekit_sip.answered",
            call_id=str(telephony_call_id),
            room=room_name,
            identity=result.identity,
        )

        # Wait for the call to end: the caller's SIP participant leaves the
        # room (hangup) or the agent runner finishes (idle timeout / stop).
        await self._await_call_end(room_name, sip_identity=result.identity)

        duration = max(0, int((datetime.utcnow() - answered_at).total_seconds()))
        await asyncio.to_thread(
            self._apply_status_update,
            telephony_call_id=telephony_call_id,
            status=CALL_STATUS_COMPLETED,
            ended_at=datetime.utcnow(),
            duration_seconds=duration,
            extra_merge={"dial_mode": "livekit_sip"},
        )
        await self._record_event(
            event_type="completed",
            call_sid=result.sip_call_id,
            telephony_call_id=telephony_call_id,
            organization_id=organization_id,
            source="livekit",
            payload={"duration_seconds": duration},
        )
        await self._registry.stop(room_name, wait=False)
        log.info(
            "telephony.livekit_sip.completed",
            call_id=str(telephony_call_id),
            room=room_name,
            duration_seconds=duration,
        )

    async def _await_call_end(
        self,
        room_name: str,
        *,
        sip_identity: str,
        poll_seconds: float = 2.0,
        max_seconds: float = 1800.0,
    ) -> None:
        """Block until the PSTN caller leaves the room or the agent ends."""

        runner = self._registry.get(room_name)
        waited = 0.0
        # Give the participant list a moment to reflect the new SIP leg.
        seen = False
        while waited < max_seconds:
            await asyncio.sleep(poll_seconds)
            waited += poll_seconds

            if runner is not None and not runner.is_running:
                return

            try:
                identities = await self._livekit.list_participant_identities(
                    room_name
                )
            except Exception:  # pragma: no cover — defensive
                continue

            present = sip_identity in identities
            if present:
                seen = True
                continue
            # Only treat absence as hangup once we've actually seen the
            # caller (avoids a startup race before SIP fully registers).
            if seen:
                return
            # If after ~10s the SIP leg never showed and the room has no
            # non-agent participants, bail out too.
            if waited >= 10.0 and not any(
                i not in ("ai-agent", "ai-stt-agent") for i in identities
            ):
                return

    # ------------------------------------------------------------------
    # Webhook handling
    # ------------------------------------------------------------------

    async def handle_status_webhook(
        self,
        *,
        params: dict[str, Any],
    ) -> TelephonyCall | None:
        """Apply a Twilio status callback to ``telephony_calls``.

        ``params`` is the raw form-encoded body (e.g.
        ``{"CallSid": ..., "CallStatus": ..., "CallDuration": ...}``).
        Unknown SIDs are logged and dropped — Twilio occasionally
        retries callbacks after a row has been GC'd in dev.
        """

        call_sid = params.get("CallSid")
        twilio_status = (params.get("CallStatus") or "").lower()
        if not call_sid:
            log.warning("telephony.webhook.missing_sid", params=params)
            return None

        mapped = _TWILIO_STATUS_MAP.get(twilio_status, twilio_status or "unknown")

        # Read row first.
        row = await asyncio.to_thread(self._fetch_by_sid, call_sid)
        if row is None:
            log.warning(
                "telephony.webhook.unknown_sid",
                call_sid=call_sid,
                twilio_status=twilio_status,
            )
            await self._record_event(
                event_type=twilio_status or "unknown",
                call_sid=call_sid,
                source="twilio",
                payload=params,
            )
            return None

        now = datetime.utcnow()
        initiated_at = now if mapped == CALL_STATUS_INITIATED else None
        ringing_at = now if mapped == "ringing" else None
        answered_at = (
            now if mapped == "in-progress" else None
        )
        ended_at = now if mapped in TERMINAL_STATUSES else None
        duration_seconds = _parse_int(params.get("CallDuration"))
        price = _parse_float(params.get("Price"))
        price_unit = params.get("PriceUnit")
        error_code = params.get("ErrorCode")
        error_message = params.get("ErrorMessage")

        # Apply.
        row = await asyncio.to_thread(
            self._apply_status_update,
            telephony_call_id=row.id,
            status=mapped,
            initiated_at=initiated_at,
            ringing_at=ringing_at,
            answered_at=answered_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            price=price,
            price_unit=price_unit,
            error_code=error_code,
            error_message=error_message,
            extra_merge={"last_twilio_status": twilio_status},
        )

        # Append event.
        await self._record_event(
            event_type=twilio_status or mapped,
            call_sid=call_sid,
            telephony_call_id=row.id,
            organization_id=row.organization_id,
            source="twilio",
            payload=params,
        )

        log.info(
            "telephony.webhook.applied",
            call_sid=call_sid,
            twilio_status=twilio_status,
            mapped_status=mapped,
            duration_seconds=duration_seconds,
            error_code=error_code,
        )

        # If terminal, signal the AI agent to wrap up.
        if mapped in TERMINAL_STATUSES:
            await self._registry.stop(row.room_name, wait=False)
            await self._record_event(
                event_type="ai_agent_stopped",
                call_sid=call_sid,
                telephony_call_id=row.id,
                organization_id=row.organization_id,
                source="internal",
                payload={"final_status": mapped},
            )

        return row

    # ------------------------------------------------------------------
    # TwiML for /webhooks/voice
    # ------------------------------------------------------------------

    def build_voice_twiml(
        self,
        *,
        room_name: str,
        opening_say: str | None = None,
    ) -> str:
        return self._twilio.build_voice_twiml(
            room_name=room_name,
            opening_say=opening_say,
        )

    async def handle_inbound_voice(
        self,
        *,
        call_sid: str,
        from_number: str | None,
        to_number: str | None,
        explicit_room: str | None = None,
    ) -> tuple[str, str | None]:
        """Voice webhook entry point.

        Returns ``(room_name, opening_line_or_none)``. The router uses the
        room name to build the SIP TwiML.

        Two cases:

        * Outbound (we originated this call): ``call_sid`` was set on a
          ``telephony_calls`` row by :meth:`initiate_outbound`. The row's
          stored ``room_name`` is returned and the agent runner is
          already in the room.

        * Inbound (someone dialled our Twilio number): no row exists yet.
          We create one, mint a fresh room, spawn an AI agent runner
          with the default persona, and return the new room name. The
          ``ai_agent_started`` event is logged for parity with outbound.
        """

        existing = await asyncio.to_thread(self._fetch_by_sid, call_sid)
        if existing is not None:
            # Outbound path — orchestrator already running. We return no
            # ``opening_say`` on purpose: the AI agent speaks the opening
            # line via ElevenLabs once it detects the caller in the room.
            # Emitting a Twilio <Say> here would double the opener with a
            # different (Twilio) voice and mask pipeline issues.
            return existing.room_name, None

        # Inbound path — bootstrap.
        room_name = explicit_room or self._generate_room_name(None)
        opening_line = (
            "Hi, this is the Aifficient AI assistant — how can I help?"
        )
        persona = settings.AI_DEFAULT_PERSONA
        framework = settings.AI_QUALIFICATION_FRAMEWORK

        row = await asyncio.to_thread(
            self._insert_call_row,
            organization_id=None,
            created_by=None,
            room_name=room_name,
            from_number=from_number or "unknown",
            to_number=to_number or self._twilio.phone_number,
            lead_id=None,
            lead_name=None,
            lead_phone=from_number,
            campaign_id=None,
            persona=persona,
            framework=framework,
            opening_line=opening_line,
            extra_context=None,
            parent_call_id=None,
            retry_count=0,
        )

        # Tag the row as inbound + bind it to the inbound CallSid so
        # subsequent /webhooks/status hits land on it.
        await asyncio.to_thread(
            self._bind_inbound_row,
            telephony_call_id=row.id,
            call_sid=call_sid,
        )

        runner = CallAgentRunner(
            room_name=room_name,
            call_id=room_name,
            organization_id=None,
            created_by=None,
            persona=persona,
            framework=framework,
            opening_line=opening_line,
            extra_context=self._build_agent_context(
                lead_name=None,
                lead_phone=from_number,
                extra=None,
            ),
        )
        await self._registry.register(runner)

        await self._record_event(
            event_type="inbound_received",
            call_sid=call_sid,
            telephony_call_id=row.id,
            source="twilio",
            payload={
                "from": from_number,
                "to": to_number,
            },
        )
        await self._record_event(
            event_type="ai_agent_started",
            call_sid=call_sid,
            telephony_call_id=row.id,
            source="internal",
            payload={"room": room_name, "inbound": True},
        )

        log.info(
            "telephony.inbound.bootstrapped",
            call_sid=call_sid,
            room=room_name,
            from_=from_number,
            to=to_number,
        )
        # Opening line is spoken by the AI agent via ElevenLabs once the
        # caller is detected in the room — not via Twilio <Say>.
        return room_name, None

    # ------------------------------------------------------------------
    # Retry / cancel
    # ------------------------------------------------------------------

    async def retry(
        self,
        *,
        call_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
    ) -> TelephonyCall:
        """Re-dial a previously-failed call.

        Reuses the lead/campaign metadata + opening_line, but mints a
        fresh room + Twilio SID. ``retry_count`` is incremented and the
        new row's ``parent_call_id`` points at the original.
        """

        original = await asyncio.to_thread(self._fetch_by_id, call_id)
        if original is None:
            raise CallNotFoundError(f"call {call_id} not found")

        if original.retry_count >= settings.TWILIO_MAX_RETRIES:
            raise TelephonyError(
                f"retry limit ({settings.TWILIO_MAX_RETRIES}) reached",
                status_code=409,
            )

        extra = dict(original.extra or {})
        opening_line = extra.get("opening_line")
        persona = extra.get("persona")
        framework = extra.get("framework")
        extra_context = extra.get("extra_context") or {}

        # Polite back-off so we don't hammer the carrier.
        if settings.TWILIO_RETRY_BACKOFF_SECONDS > 0:
            await asyncio.sleep(settings.TWILIO_RETRY_BACKOFF_SECONDS)

        return await self.initiate_outbound(
            to_number=original.to_number,
            organization_id=organization_id,
            created_by=created_by,
            from_number=original.from_number,
            lead_id=original.lead_id,
            lead_name=original.lead_name,
            lead_phone=original.lead_phone,
            campaign_id=original.campaign_id,
            playbook_id=getattr(original, "playbook_id", None),
            persona=persona,
            framework=framework,
            opening_line=opening_line,
            extra_context=extra_context,
            parent_call_id=original.id,
            retry_count=original.retry_count + 1,
        )

    async def cancel(
        self,
        *,
        call_id: uuid.UUID,
        organization_id: uuid.UUID | None,
    ) -> TelephonyCall:
        row = await asyncio.to_thread(self._fetch_by_id, call_id)
        if row is None:
            raise CallNotFoundError(f"call {call_id} not found")
        if row.status in TERMINAL_STATUSES:
            return row

        if row.call_sid:
            try:
                await self._twilio.hangup(row.call_sid)
            except TwilioProviderError as exc:
                log.warning(
                    "telephony.cancel.hangup_failed",
                    call_id=str(call_id),
                    call_sid=row.call_sid,
                    error=exc.message,
                )

        row = await asyncio.to_thread(
            self._apply_status_update,
            telephony_call_id=row.id,
            status=CALL_STATUS_CANCELED,
            ended_at=datetime.utcnow(),
            duration_seconds=None,
            error_code=None,
            error_message=None,
            extra_merge={"canceled": True},
        )
        await self._registry.stop(row.room_name, wait=False)
        await self._record_event(
            event_type="canceled",
            call_sid=row.call_sid,
            telephony_call_id=row.id,
            organization_id=row.organization_id,
            source="internal",
            payload={"by": str(organization_id) if organization_id else None},
        )
        return row

    # ------------------------------------------------------------------
    # Read APIs
    # ------------------------------------------------------------------

    async def get_call(self, call_id: uuid.UUID) -> TelephonyCall | None:
        return await asyncio.to_thread(self._fetch_by_id, call_id)

    async def get_call_by_sid(self, call_sid: str) -> TelephonyCall | None:
        return await asyncio.to_thread(self._fetch_by_sid, call_sid)

    async def list_calls(
        self,
        *,
        organization_id: uuid.UUID | None,
        limit: int = 50,
        status: str | None = None,
    ) -> list[TelephonyCall]:
        return list(
            await asyncio.to_thread(
                self._list_recent,
                organization_id=organization_id,
                limit=limit,
                status=status,
            )
        )

    # ------------------------------------------------------------------
    # DB helpers (sync; called via to_thread)
    # ------------------------------------------------------------------

    def _insert_call_row(
        self,
        *,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
        room_name: str,
        from_number: str,
        to_number: str,
        lead_id: uuid.UUID | None,
        lead_name: str | None,
        lead_phone: str | None,
        campaign_id: uuid.UUID | None,
        persona: str,
        framework: str,
        opening_line: str | None,
        extra_context: dict | None,
        parent_call_id: uuid.UUID | None,
        retry_count: int,
        playbook_id: uuid.UUID | None = None,
    ) -> TelephonyCall:
        extra = {
            "persona": persona,
            "framework": framework,
            "extra_context": extra_context or {},
        }
        if opening_line:
            extra["opening_line"] = opening_line
        if playbook_id:
            extra["playbook_id"] = str(playbook_id)
        with _db_scope() as db:
            row = TelephonyCallRepository.create(
                db,
                organization_id=organization_id,
                created_by=created_by,
                room_name=room_name,
                from_number=from_number,
                to_number=to_number,
                lead_id=lead_id,
                lead_name=lead_name,
                lead_phone=lead_phone,
                campaign_id=campaign_id,
                playbook_id=playbook_id,
                extra=extra,
                parent_call_id=parent_call_id,
                retry_count=retry_count,
            )
            return _detach_call(db, row)

    @staticmethod
    def _load_playbook(
        *,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
    ):
        from modules.playbook.service import PlaybookService

        with _db_scope() as db:
            return PlaybookService.resolve_for_call(
                db,
                organization_id=organization_id,
                playbook_id=playbook_id,
            )

    def _bind_inbound_row(
        self,
        *,
        telephony_call_id: uuid.UUID,
        call_sid: str,
    ) -> TelephonyCall:
        """Bind a freshly-created inbound row to its Twilio CallSid."""

        with _db_scope() as db:
            row = TelephonyCallRepository.get(db, telephony_call_id)
            if row is None:
                raise CallNotFoundError(
                    f"call {telephony_call_id} not found"
                )
            row.direction = "inbound"
            TelephonyCallRepository.set_sid(db, row, call_sid)
            TelephonyCallRepository.update_status(
                db,
                row,
                status="in-progress",
                initiated_at=datetime.utcnow(),
                answered_at=datetime.utcnow(),
            )
            return _detach_call(db, row)

    def _set_sid(
        self,
        *,
        telephony_call_id: uuid.UUID,
        call_sid: str,
        status: str,
    ) -> TelephonyCall:
        with _db_scope() as db:
            row = TelephonyCallRepository.get(db, telephony_call_id)
            if row is None:
                raise CallNotFoundError(
                    f"call {telephony_call_id} not found"
                )
            TelephonyCallRepository.set_sid(db, row, call_sid)
            TelephonyCallRepository.update_status(
                db,
                row,
                status=status,
                initiated_at=datetime.utcnow(),
            )
            return _detach_call(db, row)

    def _apply_status_update(
        self,
        *,
        telephony_call_id: uuid.UUID,
        status: str,
        initiated_at: datetime | None = None,
        ringing_at: datetime | None = None,
        answered_at: datetime | None = None,
        ended_at: datetime | None = None,
        duration_seconds: int | None = None,
        price: float | None = None,
        price_unit: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        extra_merge: dict | None = None,
    ) -> TelephonyCall:
        with _db_scope() as db:
            row = TelephonyCallRepository.get(db, telephony_call_id)
            if row is None:
                raise CallNotFoundError(
                    f"call {telephony_call_id} not found"
                )
            updated = TelephonyCallRepository.update_status(
                db,
                row,
                status=status,
                initiated_at=initiated_at,
                ringing_at=ringing_at,
                answered_at=answered_at,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
                price=price,
                price_unit=price_unit,
                error_code=error_code,
                error_message=error_message,
                extra_merge=extra_merge,
            )
            return _detach_call(db, updated)

    def _fetch_by_id(self, call_id: uuid.UUID) -> TelephonyCall | None:
        with _db_scope() as db:
            return _detach_call(db, TelephonyCallRepository.get(db, call_id))

    def _fetch_by_sid(self, call_sid: str) -> TelephonyCall | None:
        with _db_scope() as db:
            return _detach_call(
                db, TelephonyCallRepository.get_by_sid(db, call_sid)
            )

    def _list_recent(
        self,
        *,
        organization_id: uuid.UUID | None,
        limit: int,
        status: str | None,
    ):
        with _db_scope() as db:
            rows = TelephonyCallRepository.list_recent(
                db,
                organization_id=organization_id,
                limit=limit,
                status=status,
            )
            return _detach_calls(db, rows)

    async def _record_event(
        self,
        *,
        event_type: str,
        call_sid: str | None = None,
        telephony_call_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        source: str = "twilio",
        payload: dict[str, Any] | None = None,
    ) -> None:
        def _write() -> None:
            with _db_scope() as db:
                TelephonyEventRepository.append(
                    db,
                    event_type=event_type,
                    call_sid=call_sid,
                    telephony_call_id=telephony_call_id,
                    organization_id=organization_id,
                    source=source,
                    payload=payload,
                )

        try:
            await asyncio.to_thread(_write)
        except Exception:  # pragma: no cover — event log is best-effort
            log.exception(
                "telephony.event.write_failed",
                event_type=event_type,
                call_sid=call_sid,
            )

    async def _mark_failed(
        self,
        telephony_call_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        error_code: str,
        error_message: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._apply_status_update,
                telephony_call_id=telephony_call_id,
                status=CALL_STATUS_FAILED,
                ended_at=datetime.utcnow(),
                error_code=error_code,
                error_message=error_message,
                extra_merge={"failed_in": "initiate"},
            )
        except CallNotFoundError:  # pragma: no cover
            pass
        await self._record_event(
            event_type="failed",
            telephony_call_id=telephony_call_id,
            organization_id=organization_id,
            source="internal",
            payload={
                "error_code": error_code,
                "error_message": error_message,
            },
        )

    # ------------------------------------------------------------------
    # Pre-warm LiveKit room (used by initiate path when caller wants the
    # room created up-front, e.g. for a CSAT preview).
    # ------------------------------------------------------------------

    async def ensure_room(self, room_name: str):
        try:
            return await self._livekit.create_room(
                CreateRoomRequest(name=room_name, max_participants=4)
            )
        except LiveKitError as exc:
            if exc.status_code != 409:
                raise
            return await self._livekit.get_room(room_name)

    def _upsert_livekit_session(
        self,
        *,
        room_name: str,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
        livekit_sid: str | None,
    ) -> None:
        with _db_scope() as db:
            existing = LiveKitSessionRepository.get_by_room(db, room_name)
            if existing is None:
                LiveKitSessionRepository.create(
                    db,
                    LiveKitSession(
                        organization_id=organization_id,
                        created_by=created_by,
                        room_name=room_name,
                        livekit_sid=livekit_sid,
                        status="active",
                        extra={"source": "telephony"},
                    ),
                )
            else:
                LiveKitSessionRepository.mark_status(
                    db,
                    existing,
                    status="active",
                    livekit_sid=livekit_sid,
                )

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_room_name(organization_id: uuid.UUID | None) -> str:
        org_prefix = (
            str(organization_id)[:8] if organization_id else "anon"
        )
        return f"call-{org_prefix}-{uuid.uuid4().hex[:10]}"

    @staticmethod
    def _build_agent_context(
        *,
        lead_name: str | None,
        lead_phone: str | None,
        extra: dict | None,
    ) -> dict:
        ctx: dict[str, Any] = {
            "lead_name": lead_name or "there",
            "lead_phone": lead_phone or "",
        }
        if extra:
            ctx.update(extra)
        return ctx


def _sip_status_to_call_status(code: int | None) -> tuple[str, str | None]:
    """Map a SIP response code to our canonical call status + error code."""

    if code is None:
        return CALL_STATUS_FAILED, "sip_failed"
    if code in (486, 600):  # Busy Here / Busy Everywhere
        return "busy", str(code)
    if code in (480, 408, 487, 603):  # Unavailable / Timeout / Cancelled / Decline
        return "no-answer", str(code)
    if code == 404:  # Not Found
        return CALL_STATUS_FAILED, "404"
    return CALL_STATUS_FAILED, str(code)


def _parse_int(v: Any) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Local time helper — exposed so the timezone-aware ISO string the API
# returns is consistent across the codebase.
# ---------------------------------------------------------------------------


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
