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
        sample_rate: int = 48000,
        idle_timeout_seconds: float = 60.0,
        publish_metrics: bool = True,
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
        self._sample_rate = sample_rate
        self._idle_timeout_seconds = idle_timeout_seconds
        self._publish_metrics = publish_metrics

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
        await self._state_machine.transition(
            ConversationState.LISTENING, reason="call_started"
        )

        async with self._tts_streamer.open_session(room=self._room) as tts_session:
            async with self._stt_streamer.open_session(
                room=self._room,
                target_participant=self._target_participant,
                sample_rate=self._sample_rate,
                num_channels=1,
            ) as stt_session:
                # Speak the opening line first so the lead hears something
                # the moment the agent connects.
                if self._opening_line:
                    await self._safe_speak(tts_session, self._opening_line)

                loop_task = asyncio.create_task(
                    self._event_loop(stt_session, tts_session),
                    name=f"orch:{self._call_id}",
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
                    await loop_task
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
            "ai.orchestrator.barge_in",
            call_id=self._call_id,
            source=source,
            stt_ts_ms=event_ts_ms,
            trigger_latency_ms=trigger_latency_ms,
            silence_latency_ms=result.silence_latency_ms,
            dropped_buffer_ms=result.dropped_buffer_ms,
            was_speaking=result.was_speaking,
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

        await self._state_machine.transition(
            ConversationState.AI_SPEAKING, reason="ai_reply"
        )
        await self._safe_speak(tts_session, result.reply)

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

        async def _runner() -> None:
            try:
                await tts_session.speak(text, wait_for_playout=False)
            except BargeInInterrupted:
                log.info(
                    "ai.orchestrator.tts_interrupted",
                    call_id=self._call_id,
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
