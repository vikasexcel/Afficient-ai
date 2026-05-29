"""Live conversation loop: STT → GPT-4o → TTS, with barge-in.

This is the runtime that actually drives a phone call. It is intended to
be spawned per LiveKit room — typically by a worker process — not from
inside an HTTP request handler.

Architecture
------------
* One :class:`STTSession` listens to the human participant.
* One :class:`TTSSession` publishes the agent's voice into the same room.
* :class:`ConversationOrchestrator` glues them via :class:`AIService`:
    - On each FINAL transcript, ask GPT-4o for a reply and have TTS speak it.
    - On the next SPEECH_STARTED event while TTS is mid-utterance, call
      ``TTSSession.interrupt()`` (barge-in). The LLM call for the next turn
      will start once the new FINAL arrives.
* All persistence (transcripts, qualification, summaries) happens through
  :class:`AIService` so the HTTP surface and the live loop stay aligned.

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
from modules.ai.exceptions import AIError
from modules.ai.qualification import QualificationFramework
from modules.ai.service import AIService
from modules.stt.schema import TranscriptEventKind
from modules.stt.streamer import STTSession, STTStreamer
from modules.tts.streamer import BargeInInterrupted, TTSSession, TTSStreamer

log = get_logger("ai.orchestrator")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorStats:
    """Per-call aggregate counters for ad-hoc dashboards/tests."""

    turns: int = 0
    barge_ins: int = 0
    llm_errors: int = 0
    tts_errors: int = 0
    first_reply_ms: int | None = None
    qualification_status: str = "not_started"
    qualification_score: int = 0
    finals_seen: int = 0
    partials_seen: int = 0


@dataclass
class _LoopState:
    speak_task: asyncio.Task | None = None
    last_user_finals: list[str] = field(default_factory=list)


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
        extra_context: dict | None = None,
        organization_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        opening_line: str | None = None,
        sample_rate: int = 48000,
        idle_timeout_seconds: float = 60.0,
    ) -> None:
        self._ai = ai
        self._stt_streamer = stt_streamer
        self._tts_streamer = tts_streamer
        self._room = room
        # call_id defaults to the room name so the AI logs are easy to
        # correlate with the LiveKit, STT, and TTS logs.
        self._call_id = call_id or room
        self._target_participant = target_participant
        self._persona = persona
        self._framework = framework
        self._extra_context = extra_context or {}
        self._organization_id = organization_id
        self._created_by = created_by
        self._opening_line = opening_line
        self._sample_rate = sample_rate
        self._idle_timeout_seconds = idle_timeout_seconds

        self._stats = OrchestratorStats()
        self._state = _LoopState()
        self._call_started_at: float | None = None
        self._stop = asyncio.Event()

    @property
    def call_id(self) -> str:
        return self._call_id

    @property
    def stats(self) -> OrchestratorStats:
        return self._stats

    @property
    def room(self) -> str:
        return self._room

    def stop(self) -> None:
        """Request a graceful shutdown of the loop."""

        self._stop.set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def run(self) -> AsyncIterator["ConversationOrchestrator"]:
        """Open STT/TTS sessions, drive the loop, finalize on exit."""

        await self._ai.start_call(
            call_id=self._call_id,
            persona=self._persona,
            framework=self._framework,
            organization_id=self._organization_id,
            created_by=self._created_by,
            extra_context=self._extra_context,
        )

        self._call_started_at = time.perf_counter()

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
                    self._event_loop(stt_session, tts_session)
                )
                try:
                    yield self
                    # Wait for the loop to finish (stop() set or STT closed).
                    await loop_task
                finally:
                    loop_task.cancel()
                    try:
                        await loop_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    await self._cleanup_speak_task(tts_session)

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
                    if tts_session.is_speaking:
                        self._stats.barge_ins += 1
                        log.info(
                            "ai.orchestrator.barge_in",
                            call_id=self._call_id,
                            ts_ms=event.ts_ms,
                        )
                        await tts_session.interrupt()

                elif event.kind == TranscriptEventKind.PARTIAL:
                    self._stats.partials_seen += 1

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
            log.exception(
                "ai.orchestrator.loop_failed", call_id=self._call_id
            )

    async def _handle_user_turn(
        self, tts_session: TTSSession, user_text: str
    ) -> None:
        try:
            result = await self._ai.respond_turn(
                call_id=self._call_id,
                user_input=user_text,
                organization_id=self._organization_id,
            )
        except AIError as exc:
            self._stats.llm_errors += 1
            log.warning(
                "ai.orchestrator.llm_failed",
                call_id=self._call_id,
                error=exc.message,
                status_code=exc.status_code,
            )
            await self._safe_speak(
                tts_session,
                "Sorry, I had a brief issue on my end. Could you repeat that?",
            )
            return

        self._stats.turns += 1
        self._stats.qualification_status = result.qualification.status
        self._stats.qualification_score = result.qualification.score
        if self._stats.first_reply_ms is None:
            self._stats.first_reply_ms = result.stats.latency_ms

        if result.qualification.status == "disqualified":
            await self._safe_speak(
                tts_session,
                "Understood — I’ll take you off the list. Thanks for your time.",
            )
            self.stop()
            return

        await self._safe_speak(tts_session, result.reply)

    async def _safe_speak(self, tts_session: TTSSession, text: str) -> None:
        """Run TTSSession.speak in a task so the event loop can interrupt it."""

        await self._cleanup_speak_task(tts_session)

        async def _runner() -> None:
            try:
                await tts_session.speak(text, wait_for_playout=False)
            except BargeInInterrupted:
                log.info(
                    "ai.orchestrator.tts_interrupted",
                    call_id=self._call_id,
                )
            except Exception as exc:
                self._stats.tts_errors += 1
                log.warning(
                    "ai.orchestrator.tts_failed",
                    call_id=self._call_id,
                    error=str(exc),
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
