"""Barge-in detection latency benchmark.

Two components matter:

* the time from STT signalling speech_started (or a long-enough PARTIAL)
  to the cooldown gate releasing, AND
* the time from "interrupt requested" to the InterruptionLog write
  completing in Redis (so we know the agent silence latency was recorded).

We use a stand-in fake TTS session that mirrors the public surface of
:class:`modules.tts.streamer.TTSSession` (``is_speaking`` + ``interrupt()``)
but with a configurable simulated audio queue. This keeps the benchmark
hermetic while still exercising the real :class:`InterruptionLog`
backed by Redis.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest
import redis

from config.settings import settings
from modules.ai.interruption import (
    InterruptionEvent,
    InterruptionLog,
    InterruptionMetrics,
)
from modules.ai.memory import ConversationMemory
from modules.tts.streamer import InterruptResult
from tests._support.benchmark import measure, measure_async


def _redis_available() -> bool:
    try:
        return bool(redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.latency,
    pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable"),
]


ITERATIONS = int(os.environ.get("BENCH_BARGE_IN_ITERATIONS", "30"))


class _FakeTTSSession:
    """Minimal stand-in mirroring ``TTSSession.interrupt`` semantics.

    The simulated speak task ``sleeps`` to model audio playout; calling
    :meth:`interrupt` cancels it and reports a deterministic ``silence_latency_ms``.
    """

    def __init__(self, audio_queue_ms: int = 200) -> None:
        self._task: asyncio.Task | None = None
        self._audio_queue_ms = audio_queue_ms

    @property
    def is_speaking(self) -> bool:
        return self._task is not None and not self._task.done()

    async def speak(self, text: str) -> None:
        # Hold the channel for ~200ms (one realistic utterance length).
        async def _hold() -> None:
            await asyncio.sleep(self._audio_queue_ms / 1000.0)

        self._task = asyncio.create_task(_hold())
        try:
            await self._task
        except asyncio.CancelledError:
            raise

    async def interrupt(self) -> InterruptResult:
        t0 = time.perf_counter()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        silence_ms = int((time.perf_counter() - t0) * 1000)
        return InterruptResult(
            silence_latency_ms=silence_ms,
            dropped_buffer_ms=self._audio_queue_ms,
            was_speaking=True,
        )


def test_latency_barge_in_cooldown_check():
    """The cooldown gate is what protects us from double-barge-ins.

    It is a single ``time.monotonic()`` comparison so it has near-zero
    overhead — but the benchmark establishes a floor we can regress
    against.
    """

    cooldown_ms = settings.BARGE_IN_COOLDOWN_MS

    for _ in range(ITERATIONS):
        last = 0.0
        with measure("barge_in", "cooldown gate check"):
            now = time.monotonic()
            _allowed = (now - last) * 1000.0 >= cooldown_ms
            last = now


def test_latency_barge_in_interrupt_fake_session():
    """Time from interrupt() requested → audio buffer cleared."""

    async def go() -> None:
        for _ in range(ITERATIONS):
            session = _FakeTTSSession(audio_queue_ms=120)
            speak_task = asyncio.create_task(session.speak("hi there"))
            await asyncio.sleep(0.005)  # let the speak task actually start
            async with measure_async(
                "barge_in",
                "TTSSession.interrupt (fake)",
                metadata={"mode": "fake"},
            ):
                result = await session.interrupt()
                assert result.was_speaking
            # Wait for the cancelled speak task to actually finish.
            try:
                await speak_task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(go())


def test_latency_barge_in_event_recorded_to_redis():
    """End-to-end barge-in path includes a structured Redis log write."""

    async def go() -> None:
        memory = ConversationMemory()
        log_store = InterruptionLog(memory)
        try:
            for _ in range(ITERATIONS):
                call_id = f"bench-{uuid.uuid4().hex[:8]}"
                event = InterruptionEvent(
                    call_id=call_id,
                    ts_unix=time.time(),
                    stt_event_ts_ms=120,
                    trigger_latency_ms=15,
                    silence_latency_ms=42,
                    source="speech_started",
                    state_before="SPEAKING",
                    partial_text=None,
                )
                async with measure_async(
                    "barge_in", "InterruptionLog.record (Redis)"
                ):
                    await log_store.record(event)
                # Cleanup the per-call list.
                await log_store.clear(call_id)
        finally:
            await memory.aclose()

    asyncio.run(go())


def test_latency_barge_in_metrics_record_in_memory():
    """In-process metric record — no I/O. Tracks the dataclass accounting."""

    m = InterruptionMetrics()
    event = InterruptionEvent(
        call_id="x",
        ts_unix=time.time(),
        stt_event_ts_ms=100,
        trigger_latency_ms=15,
        silence_latency_ms=42,
        source="speech_started",
        state_before="SPEAKING",
    )
    for _ in range(ITERATIONS * 3):
        with measure("barge_in", "InterruptionMetrics.record"):
            m.record(event)
