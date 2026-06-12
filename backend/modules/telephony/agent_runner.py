"""Per-call AI agent runner.

A ``CallAgentRunner`` spawns a background asyncio task that joins the
LiveKit room for a single call and drives the live STT → GPT-4o → TTS
loop via :class:`ConversationOrchestrator`. The webhook handler keeps
runners in a process-wide registry so subsequent lifecycle events
(``completed``, ``failed``, ``no-answer``, ...) can signal a graceful
stop.

The runner is intentionally decoupled from the HTTP layer: the router
fires the task on call origination and forgets about it; the task ends
itself when the call terminates, when the orchestrator hits its idle
timeout, or when ``stop()`` is called.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from common.logging import get_logger
from modules.ai.dependencies import get_ai_service
from modules.ai.orchestrator import ConversationOrchestrator
from modules.livekit.dependencies import get_livekit_service
from modules.livekit.exceptions import LiveKitError
from modules.livekit.schema import CreateRoomRequest
from modules.stt.dependencies import get_stt_streamer
from modules.tts.dependencies import get_streamer as get_tts_streamer

log = get_logger("telephony.agent_runner")


@dataclass
class CallAgentRunner:
    """Owns the orchestrator task for one call."""

    room_name: str
    call_id: str
    organization_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    persona: str | None = None
    framework: str | None = None
    playbook_id: uuid.UUID | None = None
    opening_line: str | None = None
    # Per-playbook voice override (resolved at call-start). When unset the
    # orchestrator falls back to the global ELEVENLABS_VOICE_ID.
    voice_id: str | None = None
    voice_name: str | None = None
    voice_provider: str | None = None
    extra_context: dict | None = None
    target_participant: str | None = None
    idle_timeout_seconds: float = 90.0
    # Outbound: the agent joins the room before the lead answers, so hold
    # the opening line until the caller (SIP participant) actually joins.
    wait_for_human_seconds: float = 45.0

    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _orch: ConversationOrchestrator | None = field(
        default=None, init=False, repr=False
    )

    async def start(self) -> None:
        """Kick off the orchestrator task. Idempotent."""

        if self._task is not None and not self._task.done():
            return

        self._task = asyncio.create_task(
            self._run(), name=f"call-agent:{self.call_id}"
        )

    async def stop(self, *, wait: bool = False, timeout: float = 5.0) -> None:
        """Ask the orchestrator to wrap up. Optionally await completion."""

        orch = self._orch
        if orch is not None:
            try:
                orch.stop()
            except Exception:  # pragma: no cover
                log.exception(
                    "telephony.agent_runner.stop_signal_failed",
                    call_id=self.call_id,
                )

        if not wait or self._task is None:
            return

        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.TimeoutError:
            log.warning(
                "telephony.agent_runner.stop_timeout",
                call_id=self.call_id,
                timeout=timeout,
            )
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        log.info(
            "telephony.agent_runner.starting",
            call_id=self.call_id,
            room=self.room_name,
        )
        livekit = get_livekit_service()
        ai = get_ai_service()
        stt_streamer = get_stt_streamer()
        tts_streamer = get_tts_streamer()

        # Idempotent room create — the orchestrator's STT/TTS sessions
        # need the room to already exist on the LiveKit server.
        try:
            await livekit.create_room(
                CreateRoomRequest(name=self.room_name, max_participants=4)
            )
        except LiveKitError as exc:
            # 409 means already-exists; safe to continue.
            if exc.status_code != 409:
                log.warning(
                    "telephony.agent_runner.room_create_failed",
                    call_id=self.call_id,
                    room=self.room_name,
                    error=exc.message,
                )

        # Build BookingHandler if the calendar module is configured.
        booking_handler = None
        try:
            from modules.ai.booking_handler import BookingHandler
            from modules.ai.booking_state import BookingMemory
            from modules.calendar.dependencies import get_calendar_service

            booking_handler = BookingHandler(
                calendar_svc=get_calendar_service(),
                booking_memory=BookingMemory(),
                openai_client=ai.openai,
            )
        except Exception as _bh_exc:
            log.debug(
                "telephony.agent_runner.booking_handler_unavailable",
                reason=str(_bh_exc),
            )

        self._orch = ConversationOrchestrator(
            ai=ai,
            stt_streamer=stt_streamer,
            tts_streamer=tts_streamer,
            room=self.room_name,
            call_id=self.call_id,
            target_participant=self.target_participant,
            persona=self.persona,
            framework=self.framework,
            playbook_id=self.playbook_id,
            extra_context=self.extra_context,
            organization_id=self.organization_id,
            created_by=self.created_by,
            opening_line=self.opening_line,
            voice_id=self.voice_id,
            voice_name=self.voice_name,
            voice_provider=self.voice_provider,
            idle_timeout_seconds=self.idle_timeout_seconds,
            wait_for_human_seconds=self.wait_for_human_seconds,
            is_phone_call=True,
            booking_handler=booking_handler,
        )

        try:
            async with self._orch.run():
                # Stay in-room until either the webhook fires .stop()
                # (PSTN leg ended) or the orchestrator hits idle timeout.
                await self._orch._stop.wait()  # noqa: SLF001
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "telephony.agent_runner.failed",
                call_id=self.call_id,
                room=self.room_name,
            )
        finally:
            stats = self._orch.stats if self._orch else None
            log.info(
                "telephony.agent_runner.stopped",
                call_id=self.call_id,
                room=self.room_name,
                turns=getattr(stats, "turns", None),
                barge_ins=getattr(stats, "barge_ins", None),
                first_reply_ms=getattr(stats, "first_reply_ms", None),
            )


class CallAgentRegistry:
    """Process-wide registry of active per-call runners."""

    def __init__(self) -> None:
        self._runners: dict[str, CallAgentRunner] = {}
        self._lock = asyncio.Lock()

    async def register(self, runner: CallAgentRunner) -> CallAgentRunner:
        async with self._lock:
            existing = self._runners.get(runner.call_id)
            if existing is not None and existing.is_running:
                return existing
            self._runners[runner.call_id] = runner
        await runner.start()
        return runner

    def get(self, call_id: str) -> CallAgentRunner | None:
        return self._runners.get(call_id)

    async def stop(
        self,
        call_id: str,
        *,
        wait: bool = False,
        timeout: float = 5.0,
    ) -> None:
        runner = self._runners.get(call_id)
        if runner is None:
            return
        await runner.stop(wait=wait, timeout=timeout)
        async with self._lock:
            # Only forget the runner if it's actually finished, otherwise
            # we'd race a slower cleanup.
            if not runner.is_running:
                self._runners.pop(call_id, None)

    async def stop_all(self, *, timeout: float = 5.0) -> None:
        for call_id in list(self._runners.keys()):
            await self.stop(call_id, wait=True, timeout=timeout)


_registry: CallAgentRegistry | None = None


def get_agent_registry() -> CallAgentRegistry:
    global _registry
    if _registry is None:
        _registry = CallAgentRegistry()
    return _registry


async def shutdown_agent_registry() -> None:
    global _registry
    if _registry is not None:
        await _registry.stop_all()
        _registry = None
