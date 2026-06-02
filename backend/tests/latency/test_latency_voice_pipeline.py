"""End-to-end voice pipeline latency benchmark (hermetic).

We simulate one full turn of the live loop without touching LiveKit:

    STT FINAL event → AIService.respond_turn → TTS first chunk

The fake STT / OpenAI / ElevenLabs clients have configurable per-stage
delays so the recorded total is a faithful sum of per-stage costs.
This is the canonical "what would a user feel" benchmark.

Set ``RUN_EXTERNAL_BENCH=1`` (or component-level flags) plus the
relevant API keys to upgrade individual stages to live providers — the
voice pipeline test will then mix and match.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest
import redis

from config.settings import settings
from modules.ai.memory import ConversationMemory
from modules.ai.service import AIService
from tests._support.benchmark import measure_async
from tests._support.fakes import (
    FakeDeepgramSession,
    FakeElevenLabsTTS,
    FakeOpenAIClient,
    script_speech_turn,
)


def _redis_available() -> bool:
    try:
        return bool(redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.latency,
    pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable"),
]


ITERATIONS = int(os.environ.get("BENCH_VOICE_PIPELINE_ITERATIONS", "10"))


async def _one_turn_e2e(
    *,
    ai: AIService,
    tts: FakeElevenLabsTTS,
    call_id: str,
    user_input: str,
) -> dict[str, float]:
    """Drive STT → AI → TTS for one user turn, returning per-stage timings."""

    timings: dict[str, float] = {}

    # 1. Simulate STT: iterate the scripted event stream until FINAL.
    t0 = time.perf_counter()
    session = FakeDeepgramSession(events_to_emit=script_speech_turn(final_text=user_input))
    transcript_text: str | None = None
    async for event in session.events():
        if event.is_final and event.text:
            transcript_text = event.text
            break
    timings["stt_to_final_ms"] = (time.perf_counter() - t0) * 1000.0
    assert transcript_text == user_input

    # 2. Run the AI turn (memory + GPT + qualification).
    t1 = time.perf_counter()
    result = await ai.respond_turn(
        call_id=call_id,
        user_input=transcript_text,
        persist_transcript=False,
    )
    timings["ai_turn_ms"] = (time.perf_counter() - t1) * 1000.0

    # 3. Simulate TTS: time-to-first-byte.
    t2 = time.perf_counter()
    async for _chunk in tts.stream_pcm(result.reply):
        ttfb_ms = (time.perf_counter() - t2) * 1000.0
        timings["tts_ttfb_ms"] = ttfb_ms
        break

    timings["total_ms"] = (time.perf_counter() - t0) * 1000.0
    return timings


def test_latency_voice_pipeline_end_to_end():
    """Per-turn E2E latency with deterministic fakes."""

    async def go() -> None:
        memory = ConversationMemory()
        ai = AIService(openai=FakeOpenAIClient(per_call_latency_ms=8), memory=memory)
        tts = FakeElevenLabsTTS(per_chunk_delay_ms=2, chunks_per_sentence=4)

        # Warm a single call_id so memory hits stay realistic.
        call_id = f"bench-voice-{uuid.uuid4().hex[:10]}"
        await ai.start_call(call_id=call_id, persona="outbound_sdr", framework="BANT")

        try:
            for i in range(ITERATIONS):
                async with measure_async(
                    "voice_pipeline",
                    "stt → ai → tts (one turn, fake)",
                    metadata={
                        "mode": "fake",
                        "openai_delay_ms": 8,
                        "tts_chunk_delay_ms": 2,
                    },
                ):
                    timings = await _one_turn_e2e(
                        ai=ai,
                        tts=tts,
                        call_id=call_id,
                        user_input=f"Yes that sounds great option {i}.",
                    )
                # Push the per-stage breakdown as separate samples for diag.
                from tests._support.benchmark import get_recorder

                rec = get_recorder()
                rec.record(
                    category="voice_pipeline",
                    name="stage: stt → FINAL",
                    latency_ms=timings["stt_to_final_ms"],
                    metadata={"mode": "fake"},
                )
                rec.record(
                    category="voice_pipeline",
                    name="stage: AIService.respond_turn",
                    latency_ms=timings["ai_turn_ms"],
                    metadata={"mode": "fake"},
                )
                rec.record(
                    category="voice_pipeline",
                    name="stage: TTS TTFB",
                    latency_ms=timings["tts_ttfb_ms"],
                    metadata={"mode": "fake"},
                )
        finally:
            await memory.clear_history(call_id)
            await memory.aclose()

    asyncio.run(go())


def test_latency_voice_pipeline_finalize_call():
    """How long does end-of-call summarisation take through AIService?"""

    async def go() -> None:
        memory = ConversationMemory()
        ai = AIService(openai=FakeOpenAIClient(per_call_latency_ms=10), memory=memory)
        try:
            for _ in range(5):
                call_id = f"bench-final-{uuid.uuid4().hex[:8]}"
                await ai.start_call(
                    call_id=call_id, persona="outbound_sdr", framework="BANT"
                )
                await ai.respond_turn(
                    call_id=call_id,
                    user_input="Our budget is $50k and I am the decision maker.",
                    persist_transcript=False,
                )
                async with measure_async(
                    "voice_pipeline",
                    "AIService.finalize_call (fake)",
                    metadata={"mode": "fake"},
                ):
                    await ai.finalize_call(call_id=call_id)
        finally:
            await memory.aclose()

    asyncio.run(go())
