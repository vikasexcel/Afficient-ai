"""Live conversation loop: STT → GPT-4o → TTS, with production-grade
barge-in and recovery.

This is the runtime that actually drives a phone call. It is intended to
be spawned per LiveKit room — typically by a worker process — not from
inside an HTTP request handler.

Architecture
------------
* One :class:`STTSession` listens to the human participant (with
  Deepgram auto-reconnect baked in at the session layer).
* One :class:`TTSSession` publishes the agent's voice into the same room.
  ``interrupt()`` cancels the in-flight pump *and* clears the LiveKit
  audio queue so the lead hears silence within one RTC round-trip.
* :class:`SessionStateMachine` tracks the conversation through
  :class:`ConversationState`; transitions are timestamped, logged, and
  optionally mirrored into Redis for cross-process dashboards.
* :class:`ConversationOrchestrator` glues them via :class:`AIService`:
    - On each FINAL transcript, ask GPT-4o (with bounded retries and a
      hard per-turn deadline) for a reply and have TTS speak it.
    - On SPEECH_STARTED — or, if configured, a sufficiently long PARTIAL
      — while TTS is mid-utterance, call ``TTSSession.interrupt()``
      (barge-in). The interrupt result is logged to Redis as a
      structured :class:`InterruptionEvent`.
    - On LLM / TTS failure: enter ``RECOVERY``, speak a recovery line,
      then return to ``LISTENING``.
* All persistence (transcripts, qualification, summaries, interruption
  events) happens through :class:`AIService` + :class:`InterruptionLog`
  so the HTTP surface and the live loop stay aligned.

Lifetimes
---------
The orchestrator is an async context manager. Calling code drives the
event loop until it decides the call is over (timeout, hangup detection,
disqualification, ...) and then exits the ``async with`` block — that's
what triggers ``AIService.finalize_call``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from common.logging import get_logger
from config.settings import settings
from modules.ai.exceptions import (
    AIError,
    AIMemoryError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)
from modules.ai.interruption import (
    InterruptionEvent,
    InterruptionLog,
    InterruptionMetrics,
    publish_metrics_snapshot,
)
from modules.ai.meeting import (
    MEETING_STATUS_BOOKED,
    MEETING_STATUS_NOT_BOOKED,
    MEETING_STATUS_UNKNOWN,
    detect_status as detect_meeting_status,
)
from modules.ai.booking_handler import BookingHandler
from modules.ai.qualification import QualificationFramework
from modules.ai.recovery import (
    HealthRegistry,
    RetryPolicy,
    with_retry,
    with_timeout,
)
from modules.ai.service import AIService
from modules.ai.state import (
    ConversationState,
    SessionStateMachine,
    StateStats,
    StateTransition,
)
from modules.stt.exceptions import STTError
from modules.stt.schema import TranscriptEventKind
from modules.stt.streamer import STTSession, STTStreamer
from modules.tts.exceptions import TTSError
from modules.tts.streamer import BargeInInterrupted, TTSSession, TTSStreamer

log = get_logger("ai.orchestrator")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorStats:
    """Per-call aggregate counters for dashboards/tests."""

    turns: int = 0
    barge_ins: int = 0
    llm_errors: int = 0
    tts_errors: int = 0
    stt_errors: int = 0
    first_reply_ms: int | None = None
    qualification_status: str = "not_started"
    qualification_score: int = 0
    finals_seen: int = 0
    partials_seen: int = 0
    # Recovery
    recoveries_attempted: int = 0
    recoveries_succeeded: int = 0
    recovery_failures: int = 0
    # State-machine derived
    state_stats: StateStats = field(default_factory=StateStats)
    interruption_metrics: InterruptionMetrics = field(
        default_factory=InterruptionMetrics
    )

    def as_dict(self) -> dict:
        return {
            "turns": self.turns,
            "barge_ins": self.barge_ins,
            "llm_errors": self.llm_errors,
            "tts_errors": self.tts_errors,
            "stt_errors": self.stt_errors,
            "first_reply_ms": self.first_reply_ms,
            "qualification_status": self.qualification_status,
            "qualification_score": self.qualification_score,
            "finals_seen": self.finals_seen,
            "partials_seen": self.partials_seen,
            "recoveries_attempted": self.recoveries_attempted,
            "recoveries_succeeded": self.recoveries_succeeded,
            "recovery_failures": self.recovery_failures,
            "state": self.state_stats.as_dict(),
            "interruptions": self.interruption_metrics.as_dict(),
        }


@dataclass
class _LoopState:
    speak_task: asyncio.Task | None = None
    last_user_finals: list[str] = field(default_factory=list)
    last_barge_in_at: float = 0.0  # monotonic seconds (cooldown)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ConversationOrchestrator:
    """Drives a single live conversation inside a LiveKit room."""

    def __init__(
        self,
        *,
        ai: AIService,
        stt_streamer: STTStreamer,
        tts_streamer: TTSStreamer,
        room: str,
        call_id: str | None = None,
        target_participant: str | None = None,
        persona: str | None = None,
        framework: QualificationFramework | str | None = None,
        playbook_id: uuid.UUID | None = None,
        extra_context: dict | None = None,
        organization_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        opening_line: str | None = None,
        voice_id: str | None = None,
        voice_name: str | None = None,
        voice_provider: str | None = None,
        sample_rate: int = 48000,
        idle_timeout_seconds: float = 60.0,
        publish_metrics: bool = True,
        wait_for_human_seconds: float = 0.0,
        is_phone_call: bool = False,
        booking_handler: BookingHandler | None = None,
    ) -> None:
        self._ai = ai
        self._stt_streamer = stt_streamer
        self._tts_streamer = tts_streamer
        self._room = room
        self._call_id = call_id or room
        self._target_participant = target_participant
        self._persona = persona
        self._framework = framework
        self._playbook_id = playbook_id
        self._extra_context = extra_context or {}
        self._organization_id = organization_id
        self._created_by = created_by
        self._opening_line = opening_line
        # Per-playbook voice override. ``None`` → TTS uses the global
        # ELEVENLABS_VOICE_ID default (backward compatible).
        self._voice_id = voice_id
        self._voice_name = voice_name
        self._voice_provider = voice_provider
        # VOICE_USED_IN_CALL is logged once, on the first utterance.
        self._voice_logged = False
        # FIRST_TTS_GENERATED is logged once, when the first audio is produced.
        self._first_tts_logged = False
        self._sample_rate = sample_rate
        self._idle_timeout_seconds = idle_timeout_seconds
        self._publish_metrics = publish_metrics
        # PSTN / phone-dialer calls suppress barge-in when
        # ``settings.PHONE_CALL_BARGE_IN_ENABLED`` is False (default), so PSTN
        # echo / line noise can't cut the agent off mid-utterance. Browser
        # test rooms leave this False and keep full barge-in behaviour.
        self._is_phone_call = is_phone_call
        self._booking_handler = booking_handler
        # When > 0, the orchestrator waits this long for the human caller
        # to actually join the LiveKit room before speaking the opening
        # line. Critical for outbound calls: the agent joins the room at
        # origination time, ~10-30s before the lead picks up, so without
        # this gate the ElevenLabs opener plays to an empty room.
        self._wait_for_human_seconds = wait_for_human_seconds

        # Identities of *our own* agents in the room. STT must ignore the
        # TTS agent's audio (self-echo → feedback loop) and we must not
        # mistake an agent for the human when gating the opening line.
        self._agent_identities: set[str] = {
            ident
            for ident in (
                getattr(stt_streamer, "agent_identity", None),
                getattr(tts_streamer, "agent_identity", None),
            )
            if ident
        }

        # Meeting booking status — PLACEHOLDER tracking only (no real
        # scheduling). Surfaced to logs, Redis meta, and the call summary.
        self._meeting_status = MEETING_STATUS_UNKNOWN

        self._stats = OrchestratorStats()
        self._state = _LoopState()
        self._state_machine = SessionStateMachine()
        self._health = HealthRegistry(("llm", "stt", "tts", "transport"))
        self._interruption_log = InterruptionLog(memory=ai.memory)
        self._call_started_at: float | None = None
        self._stop = asyncio.Event()

        self._state_machine.add_listener(self._on_state_change)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def call_id(self) -> str:
        return self._call_id

    @property
    def stats(self) -> OrchestratorStats:
        return self._stats

    @property
    def room(self) -> str:
        return self._room

    @property
    def state(self) -> ConversationState:
        return self._state_machine.state

    @property
    def state_machine(self) -> SessionStateMachine:
        return self._state_machine

    @property
    def health(self) -> HealthRegistry:
        return self._health

    def stop(self) -> None:
        """Request a graceful shutdown of the loop."""

        self._stop.set()

    # ------------------------------------------------------------------
    # State-machine listener
    # ------------------------------------------------------------------

    def _on_state_change(self, transition: StateTransition) -> None:
        log.info(
            "ai.orchestrator.state_transition",
            call_id=self._call_id,
            from_state=transition.from_state.value,
            to_state=transition.to_state.value,
            reason=transition.reason,
        )
        # We don't have a clean "exited from_state at" timestamp here
        # without an extra reference — best effort: the time spent in
        # from_state is the gap between this transition's ts and the
        # previous transition's ts (or call start). The state machine
        # tracks ``time_in_state_ms`` on the *current* state, and we
        # accumulate as we leave each state below.
        self._stats.state_stats.record(transition)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def run(self) -> AsyncIterator["ConversationOrchestrator"]:
        """Open STT/TTS sessions, drive the loop, finalize on exit."""

        await self._start_call_with_recovery()

        self._call_started_at = time.perf_counter()
        log.info(
            "ai.orchestrator.CALL_STARTED",
            call_id=self._call_id,
            room=self._room,
            persona=self._persona,
            playbook_id=str(self._playbook_id) if self._playbook_id else None,
        )
        if self._is_phone_call and not settings.PHONE_CALL_BARGE_IN_ENABLED:
            log.info(
                "ai.orchestrator.PHONE_BARGE_IN_DISABLED",
                call_id=self._call_id,
                room=self._room,
            )
        await self._set_meeting_status(
            MEETING_STATUS_UNKNOWN, reason="call_started"
        )
        await self._state_machine.transition(
            ConversationState.LISTENING, reason="call_started"
        )

        async with self._tts_streamer.open_session(room=self._room) as tts_session:
            async with self._stt_streamer.open_session(
                room=self._room,
                target_participant=self._target_participant,
                sample_rate=self._sample_rate,
                num_channels=1,
                ignore_identities=self._agent_identities,
            ) as stt_session:
                log.info(
                    "ai.orchestrator.LIVEKIT_CONNECTED",
                    call_id=self._call_id,
                    room=self._room,
                    ignored_agents=sorted(self._agent_identities),
                )
                # Greppable marker: the agent is now in the room with STT +
                # TTS sessions open (STT/LLM/TTS initialized). Pairs with
                # LIVEKIT_ROOM_CREATED and FIRST_TTS_GENERATED.
                log.info(
                    "AGENT_JOINED_ROOM",
                    call_id=self._call_id,
                    room=self._room,
                )

                # Gate the opening line on the human actually being in the
                # room. Otherwise the ElevenLabs opener plays to nobody
                # (outbound) and the lead only ever hears Twilio's <Say>.
                await self._await_human_then_open(tts_session)

                loop_task = asyncio.create_task(
                    self._event_loop(stt_session, tts_session),
                    name=f"orch:{self._call_id}",
                )
                log.info(
                    "ai.orchestrator.ORCHESTRATOR_STARTED",
                    call_id=self._call_id,
                    room=self._room,
                )
                metrics_task = (
                    asyncio.create_task(
                        self._metrics_loop(),
                        name=f"orch-metrics:{self._call_id}",
                    )
                    if self._publish_metrics
                    else None
                )
                try:
                    yield self
                    # Wait for the event loop to finish OR the stop signal —
                    # whichever comes first.  Without this guard, a dead STT
                    # reconnect loop can block `await loop_task` forever and
                    # prevent the `finally:` cancel from ever running.
                    stop_waiter: asyncio.Task[None] = asyncio.ensure_future(
                        self._stop.wait()
                    )
                    try:
                        await asyncio.wait(
                            [loop_task, stop_waiter],
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    finally:
                        stop_waiter.cancel()
                        try:
                            await stop_waiter
                        except (asyncio.CancelledError, Exception):
                            pass
                finally:
                    loop_task.cancel()
                    try:
                        await loop_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    if metrics_task is not None:
                        metrics_task.cancel()
                        try:
                            await metrics_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    await self._cleanup_speak_task(tts_session)
                    await self._state_machine.transition(
                        ConversationState.ENDED, reason="run_exit"
                    )

        duration_ms = (
            int((time.perf_counter() - self._call_started_at) * 1000)
            if self._call_started_at
            else None
        )
        try:
            await self._ai.finalize_call(
                call_id=self._call_id,
                organization_id=self._organization_id,
                duration_ms=duration_ms,
                meeting_status=self._meeting_status,
            )
        except AIError as exc:
            log.warning(
                "ai.orchestrator.finalize_failed",
                call_id=self._call_id,
                error=exc.message,
            )
        # Final metrics push so the dashboard sees the end state.
        if self._publish_metrics:
            await self._publish_metrics_now()

        log.info(
            "ai.orchestrator.CALL_ENDED",
            call_id=self._call_id,
            room=self._room,
            duration_ms=duration_ms,
            turns=self._stats.turns,
            meeting_status=self._meeting_status,
        )

    async def _start_call_with_recovery(self) -> None:
        """``AIService.start_call`` wrapped in a small retry shell.

        If Redis is unhealthy at call-start we want one quick retry
        before giving up — otherwise the whole call dies before we even
        connect the SIP leg.
        """

        async def _do() -> None:
            await self._ai.start_call(
                call_id=self._call_id,
                persona=self._persona,
                framework=self._framework,
                playbook_id=self._playbook_id,
                organization_id=self._organization_id,
                created_by=self._created_by,
                extra_context=self._extra_context,
            )

        try:
            await with_retry(
                _do,
                RetryPolicy(
                    max_attempts=2,
                    base_backoff_seconds=0.2,
                    retry_on=(AIMemoryError, AIProviderError),
                ),
                label="start_call",
            )
        except AIError as exc:
            self._health.get("llm").record_fatal(exc)
            raise

    # ------------------------------------------------------------------
    # Opening line / human-join gate
    # ------------------------------------------------------------------

    async def _await_human_then_open(self, tts_session: "TTSSession") -> None:
        """Wait for the human to join, then speak the opening line.

        For outbound calls the agent is in the room well before the lead
        answers. We hold the opening utterance until a non-agent (ideally
        SIP) participant appears so the lead actually hears it. If the
        wait is disabled or times out we still speak — better a slightly
        early opener than dead air.
        """

        if not self._opening_line:
            return

        waiter = getattr(tts_session, "wait_for_human", None)
        if self._wait_for_human_seconds > 0 and callable(waiter):
            try:
                human = await waiter(
                    exclude=self._agent_identities,
                    timeout=self._wait_for_human_seconds,
                )
            except Exception as exc:  # noqa: BLE001 — never block the call
                log.warning(
                    "ai.orchestrator.wait_for_human_failed",
                    call_id=self._call_id,
                    error=str(exc),
                )
                human = None

            if human:
                log.info(
                    "ai.orchestrator.CALL_ANSWERED",
                    call_id=self._call_id,
                    room=self._room,
                    participant=human,
                )
                # Lock STT onto the caller so we never pick up stray audio.
                if self._target_participant is None:
                    self._target_participant = human
            else:
                log.warning(
                    "ai.orchestrator.human_join_timeout",
                    call_id=self._call_id,
                    seconds=self._wait_for_human_seconds,
                )

        # Conversation is now live → flip the placeholder status off
        # "unknown" before the lead's first turn.
        await self._set_meeting_status(
            MEETING_STATUS_NOT_BOOKED, reason="opening_line"
        )
        await self._safe_speak(tts_session, self._opening_line, source="opening")

    # ------------------------------------------------------------------
    # Meeting status (PLACEHOLDER — no real scheduling)
    # ------------------------------------------------------------------

    async def _set_meeting_status(self, status: str, *, reason: str) -> None:
        """Record a meeting-status transition: log + Redis meta. No-ops on
        a repeat of the current status."""

        if status == self._meeting_status:
            return
        self._meeting_status = status
        # Required structured log token + the human-readable bracket form
        # called out in the spec.
        log.info(
            "ai.orchestrator.MEETING_STATUS_UPDATED",
            call_id=self._call_id,
            meeting_status=status,
            reason=reason,
        )
        log.info("[MEETING_STATUS] %s", status)
        # Best-effort persist into the call's Redis meta so dashboards and
        # the summary path can read it without re-deriving.
        try:
            meta = await self._ai.memory.get_meta(self._call_id)
            meta["meeting_status"] = status
            await self._ai.memory.set_meta(self._call_id, meta)
        except Exception:  # noqa: BLE001 — status is best-effort
            log.warning(
                "ai.orchestrator.meeting_status_persist_failed",
                call_id=self._call_id,
            )

    # ------------------------------------------------------------------
    # Event loop
    # ------------------------------------------------------------------

    async def _event_loop(
        self,
        stt_session: STTSession,
        tts_session: TTSSession,
    ) -> None:
        idle_deadline = time.monotonic() + self._idle_timeout_seconds

        try:
            async for event in stt_session.events():
                if self._stop.is_set():
                    return

                # Refresh idle deadline on any speech-related event.
                if event.kind in (
                    TranscriptEventKind.SPEECH_STARTED,
                    TranscriptEventKind.PARTIAL,
                    TranscriptEventKind.FINAL,
                ):
                    idle_deadline = time.monotonic() + self._idle_timeout_seconds

                if event.kind == TranscriptEventKind.SPEECH_STARTED:
                    if self._barge_in_suppressed(tts_session, source="speech_started"):
                        continue
                    await self._on_speech_started(
                        tts_session, event_ts_ms=event.ts_ms
                    )

                elif event.kind == TranscriptEventKind.PARTIAL:
                    self._stats.partials_seen += 1
                    if (
                        settings.BARGE_IN_ON_PARTIAL
                        and tts_session.is_speaking
                        and event.text
                        and len(event.text.strip())
                        >= settings.BARGE_IN_PARTIAL_MIN_CHARS
                    ):
                        if self._barge_in_suppressed(
                            tts_session, source="partial", partial_text=event.text
                        ):
                            continue
                        await self._trigger_barge_in(
                            tts_session,
                            source="partial",
                            event_ts_ms=event.ts_ms,
                            partial_text=event.text,
                        )

                elif event.kind == TranscriptEventKind.FINAL:
                    self._stats.finals_seen += 1
                    text = (event.text or "").strip()
                    if not text:
                        continue
                    log.info(
                        "ai.orchestrator.STT_TRANSCRIPT_RECEIVED",
                        call_id=self._call_id,
                        chars=len(text),
                        confidence=event.confidence,
                    )
                    self._state.last_user_finals.append(text)
                    await self._handle_user_turn(tts_session, text)

                # Idle bail-out
                if time.monotonic() > idle_deadline:
                    log.info(
                        "ai.orchestrator.idle_timeout",
                        call_id=self._call_id,
                        seconds=self._idle_timeout_seconds,
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Loop-level failure (e.g. STT session unrecoverable).
            self._stats.stt_errors += 1
            self._health.get("stt").record_fatal(
                Exception("event loop crashed; see exception log")
            )
            log.exception(
                "ai.orchestrator.loop_failed", call_id=self._call_id
            )

    # ------------------------------------------------------------------
    # Barge-in
    # ------------------------------------------------------------------

    def _barge_in_suppressed(
        self,
        tts_session: TTSSession,
        *,
        source: str,
        partial_text: str | None = None,
    ) -> bool:
        """Whether barge-in should be ignored for this (phone) call.

        Only suppresses while the AI is actively speaking on a PSTN/phone
        call with ``PHONE_CALL_BARGE_IN_ENABLED`` off. Browser test rooms
        (``is_phone_call=False``) are never suppressed, and listening-state
        SPEECH_STARTED events (no active utterance) pass through so normal
        turn tracking is preserved.

        NOTE: We suppress barge-in when the orchestrator is in AI_SPEAKING
        state even if TTS hasn't started streaming yet. This prevents a race
        condition where STT noise/echo cancels the TTS before any bytes are
        sent (resulting in silent turns).
        """

        if not self._is_phone_call or settings.PHONE_CALL_BARGE_IN_ENABLED:
            return False
        # Suppress when orchestrator is in AI_SPEAKING state OR TTS is actively
        # streaming — covers the gap between state transition and first audio byte.
        if self.state != ConversationState.AI_SPEAKING and not tts_session.is_speaking:
            return False

        log.info(
            "ai.orchestrator.PHONE_BARGE_IN_IGNORED",
            call_id=self._call_id,
            source=source,
            partial_text=partial_text,
        )
        return True

    async def _on_speech_started(
        self,
        tts_session: TTSSession,
        *,
        event_ts_ms: int,
    ) -> None:
        if tts_session.is_speaking:
            await self._trigger_barge_in(
                tts_session,
                source="speech_started",
                event_ts_ms=event_ts_ms,
            )
        else:
            # User started talking while we were already listening — note
            # the state so dashboards can show turn-by-turn timing.
            await self._state_machine.transition(
                ConversationState.USER_SPEAKING, reason="speech_started"
            )

    async def _trigger_barge_in(
        self,
        tts_session: TTSSession,
        *,
        source: str,
        event_ts_ms: int,
        partial_text: str | None = None,
    ) -> None:
        # Cooldown: avoid firing multiple barge-ins for the same speech burst.
        now = time.monotonic()
        cooldown_seconds = settings.BARGE_IN_COOLDOWN_MS / 1000
        if now - self._state.last_barge_in_at < cooldown_seconds:
            self._stats.interruption_metrics.cooldown_skipped += 1
            return
        self._state.last_barge_in_at = now

        self._stats.barge_ins += 1
        state_before = self._state_machine.state.value
        await self._state_machine.transition(
            ConversationState.USER_SPEAKING, reason=f"barge_in:{source}"
        )

        trigger_started = time.monotonic()
        try:
            result = await tts_session.interrupt()
        except Exception as exc:  # noqa: BLE001
            self._stats.tts_errors += 1
            self._health.get("tts").record_failure(exc)
            log.warning(
                "ai.orchestrator.barge_in_interrupt_failed",
                call_id=self._call_id,
                error=str(exc),
            )
            return
        trigger_latency_ms = int((time.monotonic() - trigger_started) * 1000)

        event = InterruptionEvent(
            call_id=self._call_id,
            ts_unix=time.time(),
            stt_event_ts_ms=event_ts_ms,
            trigger_latency_ms=trigger_latency_ms,
            silence_latency_ms=result.silence_latency_ms,
            source=source,
            state_before=state_before,
            partial_text=partial_text,
        )
        self._stats.interruption_metrics.record(event)
        await self._interruption_log.record(event)

        log.info(
            "ai.orchestrator.BARGE_IN_TRIGGERED",
            call_id=self._call_id,
            source=source,
            partial_text=partial_text,
            was_speaking=result.was_speaking,
        )
        log.info(
            "ai.orchestrator.barge_in",
            call_id=self._call_id,
            source=source,
            stt_ts_ms=event_ts_ms,
            trigger_latency_ms=trigger_latency_ms,
            silence_latency_ms=result.silence_latency_ms,
            dropped_buffer_ms=result.dropped_buffer_ms,
            was_speaking=result.was_speaking,
            partial_text=partial_text,
        )

    # ------------------------------------------------------------------
    # User turn → LLM → TTS
    # ------------------------------------------------------------------

    async def _handle_user_turn(
        self, tts_session: TTSSession, user_text: str
    ) -> None:
        await self._state_machine.transition(
            ConversationState.PROCESSING, reason="user_final"
        )

        def _on_llm_retry(attempt: int, exc: BaseException) -> None:
            self._health.get("llm").record_retry(exc)

        async def _do_turn() -> "AIService.respond_turn":  # type: ignore[name-defined]
            return await self._ai.respond_turn(
                call_id=self._call_id,
                user_input=user_text,
                organization_id=self._organization_id,
            )

        try:
            result = await with_timeout(
                with_retry(
                    _do_turn,
                    RetryPolicy(
                        max_attempts=max(1, settings.AI_TURN_MAX_ATTEMPTS),
                        base_backoff_seconds=settings.AI_TURN_RETRY_BACKOFF_SECONDS,
                        retry_on=(
                            AIRateLimitError,
                            AITimeoutError,
                            AIProviderError,
                        ),
                        on_retry=_on_llm_retry,
                    ),
                    label="ai.turn",
                ),
                timeout_seconds=settings.AI_TURN_TIMEOUT_SECONDS,
                label="ai.turn",
            )
        except (AIError, asyncio.TimeoutError) as exc:
            self._stats.llm_errors += 1
            self._health.get("llm").record_failure(exc)
            log.warning(
                "ai.orchestrator.llm_failed",
                call_id=self._call_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            await self._enter_recovery(
                tts_session,
                fallback_text=settings.AI_RECOVERY_LLM_FALLBACK_TEXT,
                origin="llm",
            )
            return

        # Successful turn — if we just came out of RECOVERY, count the
        # recovery as succeeded.
        self._stats.turns += 1
        self._stats.qualification_status = result.qualification.status
        self._stats.qualification_score = result.qualification.score
        if self._stats.first_reply_ms is None:
            self._stats.first_reply_ms = result.stats.latency_ms

        reply_text = result.reply or ""
        log.info(
            "ai.orchestrator.GPT_RESPONSE_GENERATED",
            call_id=self._call_id,
            turn=self._stats.turns,
            latency_ms=result.stats.latency_ms,
            reply_chars=len(reply_text),
            qualification_status=result.qualification.status,
        )
        log.info(
            "ai.orchestrator.GPT_RESPONSE_LENGTH",
            call_id=self._call_id,
            chars=len(reply_text),
            words=len(reply_text.split()),
        )
        # respond_turn persists both transcript rows (user + assistant)
        # inside AIService before returning.
        log.info(
            "ai.orchestrator.TRANSCRIPT_SAVED",
            call_id=self._call_id,
            turn=self._stats.turns,
            history_length=result.history_length,
        )

        # --- Meeting booking handler (real Google Calendar integration) ---
        if self._booking_handler is not None:
            booking_result = await self._booking_handler.process_turn(
                call_id=self._call_id,
                user_text=user_text,
                agent_text=result.reply or "",
                org_id=self._organization_id,
                lead_id=None,
                lead_email=self._extra_context.get("lead_email", ""),
                lead_name=self._extra_context.get("lead_name", ""),
                timezone=self._extra_context.get("timezone", "UTC"),
                duration_minutes=int(
                    self._extra_context.get(
                        "meeting_duration_minutes",
                        settings.CALENDAR_DEFAULT_DURATION_MINUTES,
                    )
                ),
            )
            if booking_result.meeting_booked:
                await self._set_meeting_status(MEETING_STATUS_BOOKED, reason="booked")
            if booking_result.consumed and booking_result.speak_override:
                await self._state_machine.transition(
                    ConversationState.AI_SPEAKING, reason="booking_response"
                )
                await self._safe_speak(tts_session, booking_result.speak_override, source="booking")
                return
        else:
            # Fallback: lightweight regex-based detection (no real booking)
            new_status = detect_meeting_status(
                current=self._meeting_status,
                user_text=user_text,
                agent_text=result.reply or "",
            )
            await self._set_meeting_status(new_status, reason="turn")

        if result.qualification.status == "disqualified":
            await self._state_machine.transition(
                ConversationState.AI_SPEAKING, reason="disqualified"
            )
            await self._safe_speak(
                tts_session,
                "Understood — I’ll take you off the list. Thanks for your time.",
            )
            self.stop()
            return

        if result.branch_end_call:
            await self._state_machine.transition(
                ConversationState.AI_SPEAKING, reason="branch_end_call"
            )
            await self._safe_speak(
                tts_session,
                result.reply,
            )
            self.stop()
            return

        await self._state_machine.transition(
            ConversationState.AI_SPEAKING, reason="ai_reply"
        )
        await self._safe_speak(tts_session, reply_text)

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    async def _enter_recovery(
        self,
        tts_session: TTSSession,
        *,
        fallback_text: str,
        origin: str,
    ) -> None:
        self._stats.recoveries_attempted += 1
        await self._state_machine.transition(
            ConversationState.RECOVERY, reason=f"recover:{origin}"
        )
        # Best-effort: speak the fallback line through the same TTS
        # session. If THAT fails too, we count it as a failed recovery
        # and just return to listening — the lead may hear silence but
        # at least the next user turn will be processed normally.
        try:
            await self._safe_speak(tts_session, fallback_text, source="recovery")
            self._stats.recoveries_succeeded += 1
            self._health.get(origin).record_recovery()
        except Exception as exc:  # noqa: BLE001
            self._stats.recovery_failures += 1
            log.warning(
                "ai.orchestrator.recovery_failed",
                call_id=self._call_id,
                origin=origin,
                error=str(exc),
            )
        finally:
            await self._state_machine.transition(
                ConversationState.LISTENING, reason="recovery_done"
            )

    # ------------------------------------------------------------------
    # TTS plumbing
    # ------------------------------------------------------------------

    async def _safe_speak(
        self,
        tts_session: TTSSession,
        text: str,
        *,
        source: str = "ai_reply",
    ) -> None:
        """Run TTSSession.speak in a task so the event loop can interrupt it."""

        await self._cleanup_speak_task(tts_session)
        if self.state != ConversationState.AI_SPEAKING:
            await self._state_machine.transition(
                ConversationState.AI_SPEAKING, reason=f"speak:{source}"
            )

        # Resolve the voice once and log VOICE_USED_IN_CALL on first speak.
        # Priority: per-playbook voice_id → global ELEVENLABS_VOICE_ID. A
        # custom Voice ID configured on the playbook is already stored in
        # ``voice_id``, so it transparently takes precedence here.
        voice_id = self._voice_id or None
        if not self._voice_logged:
            self._voice_logged = True
            log.info(
                "ai.orchestrator.VOICE_USED_IN_CALL",
                call_id=self._call_id,
                provider=self._voice_provider or "elevenlabs",
                voice_id=voice_id or settings.ELEVENLABS_VOICE_ID or None,
                voice_name=self._voice_name
                or ("default" if not voice_id else None),
                source="playbook" if voice_id else "env_default",
            )

        async def _runner() -> None:
            tts_started = time.monotonic()
            log.info(
                "ai.orchestrator.TTS_TEXT_LENGTH",
                call_id=self._call_id,
                source=source,
                chars=len(text),
            )
            log.info(
                "ai.orchestrator.AUDIO_PLAYBACK_STARTED",
                call_id=self._call_id,
                source=source,
                chars=len(text),
            )
            try:
                stats = await tts_session.speak(
                    text, voice_id=voice_id, wait_for_playout=False
                )
                sample_rate = settings.ELEVENLABS_SAMPLE_RATE
                bytes_streamed = getattr(stats, "bytes_streamed", 0) or 0
                audio_duration_ms = int(
                    bytes_streamed / max(sample_rate * 2, 1) * 1000
                )
                log.info(
                    "ai.orchestrator.TTS_AUDIO_GENERATED",
                    call_id=self._call_id,
                    source=source,
                    chars=len(text),
                    bytes_streamed=bytes_streamed,
                    ttfb_ms=getattr(stats, "ttfb_ms", None),
                    stream_end_ms=getattr(stats, "stream_end_ms", None),
                )
                # Greppable marker: first audio packet produced for this call
                # (the greeting, when ``source == "opening"``). Proves the
                # STT→LLM→TTS pipeline reached audio output.
                if not self._first_tts_logged and bytes_streamed:
                    self._first_tts_logged = True
                    log.info(
                        "FIRST_TTS_GENERATED",
                        call_id=self._call_id,
                        room=self._room,
                        source=source,
                        bytes_streamed=bytes_streamed,
                        chars=len(text),
                    )
                log.info(
                    "ai.orchestrator.TTS_AUDIO_DURATION",
                    call_id=self._call_id,
                    source=source,
                    audio_duration_ms=audio_duration_ms,
                    bytes_streamed=bytes_streamed,
                    sample_rate=sample_rate,
                )
                log.info(
                    "ai.orchestrator.AUDIO_PUBLISHED",
                    call_id=self._call_id,
                    source=source,
                )
                log.info(
                    "ai.orchestrator.AUDIO_PLAYBACK_COMPLETED",
                    call_id=self._call_id,
                    source=source,
                    pump_elapsed_ms=int((time.monotonic() - tts_started) * 1000),
                    audio_duration_ms=audio_duration_ms,
                )
            except BargeInInterrupted as exc:
                partial = getattr(exc, "partial", None)
                bytes_streamed = (
                    getattr(partial, "bytes_streamed", 0) if partial else 0
                )
                sample_rate = settings.ELEVENLABS_SAMPLE_RATE
                partial_audio_ms = int(
                    bytes_streamed / max(sample_rate * 2, 1) * 1000
                )
                log.info(
                    "ai.orchestrator.AUDIO_INTERRUPTED",
                    call_id=self._call_id,
                    source=source,
                    chars_requested=len(text),
                    bytes_streamed_before_interrupt=bytes_streamed,
                    partial_audio_duration_ms=partial_audio_ms,
                    pump_elapsed_ms=int((time.monotonic() - tts_started) * 1000),
                )
                log.info(
                    "ai.orchestrator.tts_interrupted",
                    call_id=self._call_id,
                    source=source,
                )
            except TTSError as exc:
                self._stats.tts_errors += 1
                self._health.get("tts").record_failure(exc)
                log.warning(
                    "ai.orchestrator.tts_failed",
                    call_id=self._call_id,
                    error=str(exc),
                )
            except Exception as exc:  # noqa: BLE001
                self._stats.tts_errors += 1
                self._health.get("tts").record_failure(exc)
                log.warning(
                    "ai.orchestrator.tts_failed_unknown",
                    call_id=self._call_id,
                    error=str(exc),
                )
            finally:
                # Done speaking → ready for next user turn (unless the
                # loop already flipped us into another state).
                if self.state == ConversationState.AI_SPEAKING:
                    await self._state_machine.transition(
                        ConversationState.LISTENING, reason="speak_done"
                    )

        self._state.speak_task = asyncio.create_task(_runner())

    async def _cleanup_speak_task(self, tts_session: TTSSession) -> None:
        task = self._state.speak_task
        if task is None:
            return
        if not task.done():
            try:
                await tts_session.interrupt()
            except Exception:
                pass
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._state.speak_task = None

    # ------------------------------------------------------------------
    # Metrics snapshot loop
    # ------------------------------------------------------------------

    async def _metrics_loop(self) -> None:
        """Push a JSON metrics snapshot to Redis every few seconds.

        Cancelled when the orchestrator exits. We don't care about
        precise cadence — analytics consumers poll at their own rate.
        """

        try:
            while not self._stop.is_set():
                await self._publish_metrics_now()
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — never crash the metrics task
            log.exception(
                "ai.orchestrator.metrics_loop_failed", call_id=self._call_id
            )

    async def _publish_metrics_now(self) -> None:
        try:
            await publish_metrics_snapshot(
                self._ai.memory,
                call_id=self._call_id,
                payload={
                    "state": self.state.value,
                    "time_in_state_ms": self._state_machine.time_in_state_ms,
                    "stats": self._stats.as_dict(),
                    "health": self._health.as_dict(),
                    "recovery_success_rate": self._health.recovery_success_rate,
                    "stt_reconnects": getattr(
                        self._state.speak_task, "reconnects", None
                    ),
                },
            )
        except Exception:  # noqa: BLE001 — best effort
            log.exception(
                "ai.orchestrator.metrics_publish_failed",
                call_id=self._call_id,
            )
