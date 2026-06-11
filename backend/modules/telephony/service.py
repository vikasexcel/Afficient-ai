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
from modules.telephony.amd import (
    AMD_UNKNOWN,
    AMD_VOICEMAIL,
    detect_answer_type,
)
from modules.campaign.voicemail import resolve_voicemail_config
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
        voicemail_enabled: bool | None = None,
        voicemail_message_url: str | None = None,
        amd_unknown_fallback: str | None = None,
        parent_call_id: uuid.UUID | None = None,
        retry_count: int = 0,
        execution_id: uuid.UUID | None = None,
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

        # Resolve AMD / voicemail-drop settings. Explicit per-call params win;
        # otherwise inherit the linked campaign's ``voicemail_config``. AMD is
        # turned on whenever voicemail drop is desired (or explicitly asked)
        # and the global ``TWILIO_AMD_ENABLED`` switch is on.
        vm_settings = await self._resolve_voicemail_settings(
            campaign_id=campaign_id,
            voicemail_enabled=voicemail_enabled,
            voicemail_message_url=voicemail_message_url,
            amd_unknown_fallback=amd_unknown_fallback,
        )
        amd_on = bool(answering_machine_detection)
        if vm_settings["voicemail_enabled"] and settings.TWILIO_AMD_ENABLED:
            amd_on = True

        log.info(
            "telephony.initiate.amd_resolved",
            org=str(organization_id) if organization_id else None,
            campaign_id=str(campaign_id) if campaign_id else None,
            amd_on=amd_on,
            amd_enabled_global=settings.TWILIO_AMD_ENABLED,
            voicemail_enabled=vm_settings["voicemail_enabled"],
            has_recording=bool(vm_settings["voicemail_message_url"]),
            unknown_fallback=vm_settings["amd_unknown_fallback"],
        )

        voicemail_extra = (
            {
                "enabled": vm_settings["voicemail_enabled"],
                "message_url": vm_settings["voicemail_message_url"],
                "unknown_fallback": vm_settings["amd_unknown_fallback"],
            }
            if (vm_settings["voicemail_enabled"] or amd_on)
            else None
        )

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
            voicemail=voicemail_extra,
            execution_id=execution_id,
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
        #
        #    IMPORTANT: LiveKit ``CreateSIPParticipant`` has no Answering
        #    Machine Detection. When AMD / voicemail drop is requested we MUST
        #    originate via Twilio (which runs AMD and posts ``AnsweredBy`` to
        #    the voice webhook so we can drop a voicemail). Twilio still
        #    bridges humans into the same agent room via <Dial><Sip> using
        #    ``LIVEKIT_SIP_URI``. Routing AMD calls down the LiveKit-SIP path
        #    silently disables the entire AMD/voicemail feature — that was the
        #    root cause of "AMD not working in actual calls".
        if settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID and amd_on:
            if not settings.LIVEKIT_SIP_URI:
                log.warning(
                    "telephony.initiate.amd_without_sip_bridge",
                    call_id=str(row.id),
                    room=effective_room,
                    detail=(
                        "AMD requires the Twilio origination path but "
                        "LIVEKIT_SIP_URI is unset; humans cannot be bridged "
                        "to the AI agent. Set LIVEKIT_SIP_URI."
                    ),
                )
            log.info(
                "telephony.initiate.amd_forces_twilio_path",
                call_id=str(row.id),
                room=effective_room,
                outbound_trunk=settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID,
                reason="livekit_sip_originate_has_no_amd",
            )

        if settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID and not amd_on:
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
                answering_machine_detection=amd_on,
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

        try:
            result = await self._livekit.create_sip_participant(
                room_name=room_name,
                to_number=to_number,
                trunk_id=settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID,
                identity="sip-caller",
            )
        except Exception as exc:
            log.exception(
                "telephony.livekit_sip.dial_failed",
                call_id=str(telephony_call_id),
                room=room_name,
                to=to_number,
            )
            await asyncio.to_thread(
                self._apply_status_update,
                telephony_call_id=telephony_call_id,
                status=CALL_STATUS_FAILED,
                ended_at=datetime.utcnow(),
                error_code="livekit_sip_dial_failed",
                error_message=str(exc),
                extra_merge={"dial_mode": "livekit_sip"},
            )
            await self._registry.stop(room_name, wait=False)
            return

        if not result.answered:
            if _should_fallback_livekit_sip_to_twilio(
                result.sip_status_code,
                result.error,
            ):
                try:
                    await self._fallback_livekit_sip_to_twilio(
                        telephony_call_id=telephony_call_id,
                        room_name=room_name,
                        to_number=to_number,
                        organization_id=organization_id,
                        sip_status_code=result.sip_status_code,
                        sip_error=result.error,
                    )
                    return
                except TelephonyError as exc:
                    log.warning(
                        "telephony.livekit_sip.fallback_twilio_failed",
                        call_id=str(telephony_call_id),
                        room=room_name,
                        to=to_number,
                        error=exc.message,
                    )

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

    async def _fallback_livekit_sip_to_twilio(
        self,
        *,
        telephony_call_id: uuid.UUID,
        room_name: str,
        to_number: str,
        organization_id: uuid.UUID | None,
        sip_status_code: int | None,
        sip_error: str | None,
    ) -> None:
        """Originate via Twilio when LiveKit SIP infrastructure is unavailable."""

        log.warning(
            "telephony.livekit_sip.fallback_twilio",
            call_id=str(telephony_call_id),
            room=room_name,
            to=to_number,
            sip_status=sip_status_code,
            sip_error=sip_error,
        )
        await self._record_event(
            event_type="livekit_sip_fallback_twilio",
            telephony_call_id=telephony_call_id,
            organization_id=organization_id,
            source="internal",
            payload={
                "sip_status_code": sip_status_code,
                "sip_error": sip_error,
            },
        )

        originated = await self._twilio.create_call(
            to_number=to_number,
            room_name=room_name,
        )
        await asyncio.to_thread(
            self._set_sid,
            telephony_call_id=telephony_call_id,
            call_sid=originated.sid,
            status=_TWILIO_STATUS_MAP.get(
                (originated.status or "").lower(),
                CALL_STATUS_INITIATED,
            ),
        )
        await asyncio.to_thread(
            self._apply_status_update,
            telephony_call_id=telephony_call_id,
            status=_TWILIO_STATUS_MAP.get(
                (originated.status or "").lower(),
                CALL_STATUS_INITIATED,
            ),
            error_code=None,
            error_message=None,
            extra_merge={"dial_mode": "twilio_fallback"},
        )
        await self._record_event(
            event_type="originated",
            call_sid=originated.sid,
            telephony_call_id=telephony_call_id,
            organization_id=organization_id,
            source="twilio",
            payload={
                "fallback_from": "livekit_sip",
                "twilio_status": originated.status,
                "to": originated.to,
                "from": originated.from_,
            },
        )
        log.info(
            "telephony.livekit_sip.fallback_twilio_originated",
            call_id=str(telephony_call_id),
            call_sid=originated.sid,
            room=room_name,
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
    # AMD / Voicemail drop
    # ------------------------------------------------------------------

    async def _resolve_voicemail_settings(
        self,
        *,
        campaign_id: uuid.UUID | None,
        voicemail_enabled: bool | None,
        voicemail_message_url: str | None,
        amd_unknown_fallback: str | None,
    ) -> dict:
        """Merge explicit per-call voicemail params with the campaign config.

        Explicit (non-None) params override; anything omitted is inherited
        from the linked campaign's ``voicemail_config``.
        """

        campaign_cfg: dict | None = None
        if campaign_id is not None:
            campaign_cfg = await asyncio.to_thread(
                self._fetch_campaign_voicemail_config, campaign_id
            )
        resolved = resolve_voicemail_config(campaign_cfg)

        enabled = (
            resolved.enabled
            if voicemail_enabled is None
            else bool(voicemail_enabled)
        )
        message_url = voicemail_message_url or resolved.message_url
        fallback = amd_unknown_fallback or resolved.unknown_fallback
        return {
            "voicemail_enabled": enabled,
            "voicemail_message_url": message_url,
            "amd_unknown_fallback": fallback,
        }

    @staticmethod
    def _fetch_campaign_voicemail_config(
        campaign_id: uuid.UUID,
    ) -> dict | None:
        from modules.campaign.model import Campaign

        with _db_scope() as db:
            campaign = db.get(Campaign, campaign_id)
            return campaign.voicemail_config if campaign else None

    def _apply_amd_update(
        self,
        *,
        telephony_call_id: uuid.UUID,
        amd_result: str | None = None,
        amd_confidence: float | None = None,
        voicemail_detected_at: datetime | None = None,
        voicemail_dropped: bool | None = None,
        voicemail_dropped_at: datetime | None = None,
        voicemail_recording_url: str | None = None,
    ) -> TelephonyCall:
        with _db_scope() as db:
            row = TelephonyCallRepository.get(db, telephony_call_id)
            if row is None:
                raise CallNotFoundError(
                    f"call {telephony_call_id} not found"
                )
            updated = TelephonyCallRepository.update_amd(
                db,
                row,
                amd_result=amd_result,
                amd_confidence=amd_confidence,
                voicemail_detected_at=voicemail_detected_at,
                voicemail_dropped=voicemail_dropped,
                voicemail_dropped_at=voicemail_dropped_at,
                voicemail_recording_url=voicemail_recording_url,
            )
            return _detach_call(db, updated)

    def build_voicemail_twiml(self, *, recording_url: str) -> str:
        return self._twilio.build_voicemail_twiml(recording_url=recording_url)

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

        # Capture AMD classification when Twilio reports it on the status
        # callback (async AMD path). The voice webhook handles the sync path.
        answered_by = params.get("AnsweredBy")
        if answered_by:
            amd = detect_answer_type(
                answered_by,
                confidence=_parse_float(params.get("MachineDetectionConfidence")),
                provider="twilio",
            )
            await asyncio.to_thread(
                self._apply_amd_update,
                telephony_call_id=row.id,
                amd_result=amd.result,
                amd_confidence=amd.confidence,
                voicemail_detected_at=(
                    now if amd.result == AMD_VOICEMAIL else None
                ),
            )
            log.info(
                "telephony.webhook.amd",
                call_sid=call_sid,
                answered_by=answered_by,
                amd_result=amd.result,
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
            # Voicemail playback tracking: a call that dropped a voicemail and
            # then reaches ``completed`` played the recording to the end; any
            # other terminal status (failed/busy/no-answer/canceled) means the
            # drop did not complete cleanly.
            if getattr(row, "voicemail_dropped", False):
                playback_ok = mapped == CALL_STATUS_COMPLETED
                playback_status = "completed" if playback_ok else "failed"
                await asyncio.to_thread(
                    self._apply_status_update,
                    telephony_call_id=row.id,
                    status=mapped,
                    extra_merge={
                        "voicemail_playback": {
                            "status": playback_status,
                            "final_call_status": mapped,
                            "duration_seconds": duration_seconds,
                        }
                    },
                )
                await self._record_event(
                    event_type=f"voicemail_playback_{playback_status}",
                    call_sid=call_sid,
                    telephony_call_id=row.id,
                    organization_id=row.organization_id,
                    source="internal",
                    payload={
                        "final_status": mapped,
                        "duration_seconds": duration_seconds,
                        "recording_url": row.voicemail_recording_url,
                    },
                )
                log.info(
                    f"telephony.voicemail.playback.{playback_status}",
                    call_sid=call_sid,
                    final_status=mapped,
                    duration_seconds=duration_seconds,
                    recording_url=row.voicemail_recording_url,
                )
                # Explicit, greppable playback-completion markers.
                log.info(
                    "VOICEMAIL_PLAY_COMPLETED"
                    if playback_ok
                    else "VOICEMAIL_PLAY_FAILED",
                    call_sid=call_sid,
                    final_status=mapped,
                    duration_seconds=duration_seconds,
                    recording_url=row.voicemail_recording_url,
                )

            await self._registry.stop(row.room_name, wait=False)
            await self._record_event(
                event_type="ai_agent_stopped",
                call_sid=call_sid,
                telephony_call_id=row.id,
                organization_id=row.organization_id,
                source="internal",
                payload={"final_status": mapped},
            )

            # Reconcile the terminal outcome back onto a linked campaign
            # execution (RC5: campaign → call → outcome → retry/metrics).
            await self._reconcile_campaign_execution(row, mapped)

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
        answered_by: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        """Voice webhook entry point.

        Returns ``(room_name, opening_line_or_none, voicemail_url_or_none)``.
        When ``voicemail_url`` is set the router plays that recording (voicemail
        drop) instead of bridging the call into the AI room.

        Two cases:

        * Outbound (we originated this call): ``call_sid`` was set on a
          ``telephony_calls`` row by :meth:`initiate_outbound`. AMD's
          ``answered_by`` (Twilio sync AMD) decides whether to continue the AI
          conversation (human / fallback) or drop a voicemail (machine).

        * Inbound (someone dialled our Twilio number): no row exists yet.
          We create one, mint a fresh room, spawn an AI agent runner
          with the default persona, and return the new room name. The
          ``ai_agent_started`` event is logged for parity with outbound.
        """

        existing = await asyncio.to_thread(self._fetch_by_sid, call_sid)
        if existing is not None:
            # Outbound path — orchestrator already running. AMD may divert the
            # call to a voicemail drop; otherwise we bridge to the AI room.
            voicemail_url = await self._handle_amd_on_answer(
                existing, answered_by
            )
            # We return no ``opening_say`` on purpose: the AI agent speaks the
            # opening line via ElevenLabs once it detects the caller in the
            # room. Emitting a Twilio <Say> here would double the opener with a
            # different (Twilio) voice and mask pipeline issues.
            return existing.room_name, None, voicemail_url

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
        return room_name, None, None

    async def handle_async_amd(
        self,
        *,
        call_sid: str,
        answered_by: str | None,
    ) -> str | None:
        """Asynchronous AMD callback entry point.

        With async AMD the call is already bridged to the AI agent by the time
        Twilio classifies the answer. If AMD decides a voicemail drop, we must
        redirect the *live* call to the recording (the synchronous path returns
        TwiML before bridging, but here the bridge already happened).

        Returns the recording URL when a drop was performed, else ``None``.
        """

        row = await asyncio.to_thread(self._fetch_by_sid, call_sid)
        if row is None:
            log.warning("telephony.amd.async_no_row", call_sid=call_sid)
            return None

        recording_url = await self._handle_amd_on_answer(row, answered_by)
        if not recording_url:
            # Human / fallback-to-human → leave the AI conversation bridged.
            return None

        # Machine detected on an already-bridged call → redirect the live leg
        # to play the voicemail recording. The agent was already stopped by
        # ``_handle_amd_on_answer``.
        twiml = self.build_voicemail_twiml(recording_url=recording_url)
        try:
            await self._twilio.redirect_call(call_sid, twiml=twiml)
            log.info(
                "VOICEMAIL_PLAY_STARTED",
                call_sid=call_sid,
                room=row.room_name,
                answered_by=answered_by,
                recording_url=recording_url,
            )
        except TelephonyError as exc:
            log.warning(
                "telephony.amd.async_redirect_failed",
                call_sid=call_sid,
                room=row.room_name,
                error=exc.message,
            )
        return recording_url

    async def _handle_amd_on_answer(
        self,
        row: TelephonyCall,
        answered_by: str | None,
    ) -> str | None:
        """Record AMD result + decide voicemail drop on call answer.

        Returns the recording URL to play when a voicemail drop should happen,
        otherwise ``None`` (continue the AI conversation).

        Decision table (per the campaign call-flow spec):

        * ``human``    -> continue AI conversation (no drop)
        * ``voicemail``-> drop if enabled + recording configured, else continue
        * ``unknown``  -> configurable fallback (default: continue)
        """

        if not answered_by:
            return None

        amd = detect_answer_type(answered_by, provider="twilio")
        vm = (row.extra or {}).get("voicemail") or {}
        now = datetime.utcnow()

        should_drop = False
        if vm.get("enabled") and vm.get("message_url"):
            if amd.result == AMD_VOICEMAIL:
                should_drop = True
            elif (
                amd.result == AMD_UNKNOWN
                and (vm.get("unknown_fallback") or "human") == AMD_VOICEMAIL
            ):
                should_drop = True

        recording_url = vm.get("message_url") if should_drop else None

        await asyncio.to_thread(
            self._apply_amd_update,
            telephony_call_id=row.id,
            amd_result=amd.result,
            amd_confidence=amd.confidence,
            voicemail_detected_at=(
                now if amd.result == AMD_VOICEMAIL else None
            ),
            voicemail_dropped=True if should_drop else None,
            voicemail_dropped_at=now if should_drop else None,
            voicemail_recording_url=recording_url,
        )

        log.info(
            "telephony.amd.on_answer",
            call_sid=row.call_sid,
            room=row.room_name,
            answered_by=answered_by,
            amd_result=amd.result,
            voicemail_drop=should_drop,
        )

        if should_drop:
            # Explicit, greppable marker for the moment voicemail drop is
            # decided on a real answered call (AMD -> machine/fallback).
            log.info(
                "VOICEMAIL_TRIGGERED",
                call_sid=row.call_sid,
                room=row.room_name,
                answered_by=answered_by,
                amd_result=amd.result,
                amd_confidence=amd.confidence,
                recording_url=recording_url,
            )
            # No AI conversation — stop the agent sitting in the room so it
            # doesn't talk over the voicemail playback, and audit the drop.
            await self._registry.stop(row.room_name, wait=False)
            await self._record_event(
                event_type="voicemail_dropped",
                call_sid=row.call_sid,
                telephony_call_id=row.id,
                organization_id=row.organization_id,
                source="internal",
                payload={
                    "recording_url": recording_url,
                    "answered_by": answered_by,
                    "amd_result": amd.result,
                },
            )
            return recording_url

        return None

    # ------------------------------------------------------------------
    # Campaign execution reconciliation (RC5)
    # ------------------------------------------------------------------

    # Twilio terminal call-status -> campaign execution outcome.
    _OUTCOME_MAP = {
        CALL_STATUS_COMPLETED: "completed",
        "no-answer": "no_answer",
        "busy": "busy",
        CALL_STATUS_FAILED: "failed",
        CALL_STATUS_CANCELED: "failed",
    }

    async def _reconcile_campaign_execution(
        self, row: TelephonyCall, mapped_status: str
    ) -> None:
        """Map a terminal call outcome back onto its campaign execution.

        When a call was placed by the campaign worker (``initiate_outbound``
        with ``execution_id``), the lifecycle finishes asynchronously via this
        webhook. We translate the final call status (and AMD/voicemail-drop
        result) into a campaign outcome and run the retry engine so metrics +
        retries advance. No-op for ad-hoc (non-campaign) calls.
        """

        extra = row.extra or {}
        execution_id = extra.get("campaign_execution_id")
        if not execution_id:
            return

        if getattr(row, "voicemail_dropped", False) or (
            row.amd_result == AMD_VOICEMAIL
        ):
            outcome = "voicemail"
        else:
            outcome = self._OUTCOME_MAP.get(mapped_status, "failed")

        try:
            await asyncio.to_thread(
                self._run_execution_outcome,
                execution_id=uuid.UUID(str(execution_id)),
                outcome=outcome,
            )
        except Exception:  # pragma: no cover - defensive
            log.exception(
                "telephony.reconcile.failed",
                execution_id=str(execution_id),
                call_id=str(row.id),
                outcome=outcome,
            )
            return

        log.info(
            "telephony.reconcile.applied",
            execution_id=str(execution_id),
            call_id=str(row.id),
            final_status=mapped_status,
            outcome=outcome,
        )

    @staticmethod
    def _run_execution_outcome(
        *, execution_id: uuid.UUID, outcome: str
    ) -> None:
        from modules.campaign.execution_model import Execution
        from modules.campaign.retry import process_outcome
        from modules.campaign.worker import _campaign_configs

        with _db_scope() as db:
            execution = db.get(Execution, execution_id)
            if execution is None:
                return

            retry_config, voicemail_config = _campaign_configs(db, execution)

            # For graph-based executions we need to advance the graph pointer
            # after the CALL completes.  Defer the commit so we can mutate the
            # execution once more before _db_scope flushes on exit.
            is_graph = execution.current_node_id is not None
            process_outcome(
                db,
                execution,
                outcome,
                retry_config=retry_config,
                voicemail_config=voicemail_config,
                commit=not is_graph,
            )

            if not is_graph:
                return  # Legacy path: already committed by process_outcome.

            # Graph path ─────────────────────────────────────────────────────
            # process_outcome set execution.status to one of:
            #   "completed"  → non-retryable outcome (call succeeded / opted-out)
            #   "failed"     → retryable + retry scheduled or exhausted
            #
            # On "completed": advance current_node_id to the next node and
            # re-enqueue so the scheduler dispatches the rest of the graph on
            # the next tick.  The CALL node's id stays recorded via node_outputs.
            #
            # On "failed": execution.retry_status is "scheduled" (backoff
            # pending) or "exhausted" — the existing retry machinery handles
            # both without any graph-specific logic.  current_node_id stays on
            # the CALL node so the re-dispatched execution retries the call.
            if execution.status != "completed":
                return  # _db_scope commits the retry/failure state.

            from modules.campaign.workflow_model import Workflow
            from modules.campaign.workflow_service import WorkflowService

            workflow = db.get(Workflow, execution.workflow_id)
            if workflow is None or not workflow.nodes:
                # Workflow missing or not a graph workflow — nothing to do.
                return

            node_id = execution.current_node_id
            next_nodes = WorkflowService.get_next_nodes(workflow, node_id)
            if not next_nodes:
                # CALL was the terminal node — execution stays completed.
                return

            # Re-enqueue at the next node; scheduler dispatches on next tick.
            execution.current_node_id = next_nodes[0]["id"]
            execution.status = "queued"
            execution.retry_status = "pending"
            # _db_scope commits on exit.

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
        vm = extra.get("voicemail") or {}

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
            voicemail_enabled=vm.get("enabled") if vm else None,
            voicemail_message_url=vm.get("message_url") if vm else None,
            amd_unknown_fallback=vm.get("unknown_fallback") if vm else None,
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

    async def delete_call(
        self,
        *,
        call_id: uuid.UUID,
        organization_id: uuid.UUID | None,
    ) -> None:
        """Permanently remove a call record + its event history.

        If the call is still in flight we best-effort cancel it first so
        we don't orphan a live Twilio leg / AI agent, then delete the row.
        Tenant scoping is enforced by the caller (router).
        """

        row = await asyncio.to_thread(self._fetch_by_id, call_id)
        if row is None:
            raise CallNotFoundError(f"call {call_id} not found")

        if row.status not in TERMINAL_STATUSES:
            try:
                await self.cancel(
                    call_id=call_id, organization_id=organization_id
                )
            except Exception as exc:  # pragma: no cover - best effort
                log.warning(
                    "telephony.delete.cancel_failed",
                    call_id=str(call_id),
                    error=str(exc),
                )

        await asyncio.to_thread(self._delete_row, call_id)
        log.info("telephony.delete.done", call_id=str(call_id))

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
        answered_by: str | None = None,
    ) -> list[TelephonyCall]:
        return list(
            await asyncio.to_thread(
                self._list_recent,
                organization_id=organization_id,
                limit=limit,
                status=status,
                answered_by=answered_by,
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
        voicemail: dict | None = None,
        execution_id: uuid.UUID | None = None,
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
        if voicemail:
            extra["voicemail"] = voicemail
        if execution_id:
            extra["campaign_execution_id"] = str(execution_id)
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

    def _delete_row(self, call_id: uuid.UUID) -> None:
        with _db_scope() as db:
            row = TelephonyCallRepository.get(db, call_id)
            if row is None:
                return
            TelephonyCallRepository.delete(db, row)

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
        answered_by: str | None = None,
    ):
        with _db_scope() as db:
            rows = TelephonyCallRepository.list_recent(
                db,
                organization_id=organization_id,
                limit=limit,
                status=status,
                answered_by=answered_by,
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


def _should_fallback_livekit_sip_to_twilio(
    code: int | None,
    error: str | None,
) -> bool:
    """Return True for LiveKit SIP infra failures, not callee outcomes."""

    text = (error or "").lower()
    if "redis required" in text or "sip not connected" in text:
        return True
    return code in (500, 503) and "twirp" in text


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
