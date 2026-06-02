"""Latency benchmarks for the Deepgram STT path.

Hermetic by default: a fake Deepgram session emits a scripted event
stream so we can measure how long the orchestrator's ``events()``
iterator takes to surface partials/finals. The live path is opt-in via
``RUN_DEEPGRAM_BENCH=1``.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from config.settings import settings
from modules.stt.deepgram_client import DeepgramSTT
from modules.stt.schema import TranscriptEventKind
from tests._support.benchmark import deepgram_enabled, measure_async
from tests._support.fakes import FakeDeepgramSession, script_speech_turn


pytestmark = pytest.mark.latency


FAKE_ITERS = int(os.environ.get("BENCH_DEEPGRAM_FAKE_ITERATIONS", "20"))


async def _drain(session: FakeDeepgramSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    async for event in session.events():
        counts[event.kind.value] = counts.get(event.kind.value, 0) + 1
    return counts


def test_latency_deepgram_session_event_drain_with_fake():
    """How long does it take to iterate one complete user turn?"""

    async def go() -> None:
        for _ in range(FAKE_ITERS):
            session = FakeDeepgramSession(events_to_emit=script_speech_turn())
            async with measure_async(
                "deepgram_stt", "events() one turn (fake)",
                metadata={"mode": "fake"},
            ):
                counts = await _drain(session)
                assert counts.get("final", 0) == 1
                assert counts.get("speech_started", 0) == 1

    asyncio.run(go())


def test_latency_deepgram_speech_started_time_to_partial():
    """Tracks the gap between SPEECH_STARTED and the first non-empty PARTIAL."""

    async def go() -> None:
        for _ in range(FAKE_ITERS):
            session = FakeDeepgramSession(events_to_emit=script_speech_turn())
            async with measure_async(
                "deepgram_stt",
                "speech_started -> partial (fake)",
                metadata={"mode": "fake"},
            ):
                saw_speech_started = False
                async for event in session.events():
                    if event.kind == TranscriptEventKind.SPEECH_STARTED:
                        saw_speech_started = True
                    if (
                        saw_speech_started
                        and event.kind == TranscriptEventKind.PARTIAL
                    ):
                        break

    asyncio.run(go())


@pytest.mark.external
@pytest.mark.skipif(
    not (deepgram_enabled() and settings.DEEPGRAM_API_KEY),
    reason="Deepgram benchmark disabled (set RUN_DEEPGRAM_BENCH=1)",
)
def test_latency_deepgram_connect_live():
    """Measures the cost of opening a fresh Deepgram websocket."""

    async def go() -> None:
        stt = DeepgramSTT()
        for _ in range(3):
            async with measure_async(
                "deepgram_stt", "open_session connect (live)",
                metadata={"mode": "live"},
            ):
                async with stt.open_session(sample_rate=16000) as session:
                    # Send one frame of silence so the connection is warm.
                    await session.send_audio(b"\x00" * 320)

    asyncio.run(go())
