"""Latency benchmarks for the ElevenLabs TTS path.

Hermetic by default — uses a fake :class:`FakeElevenLabsTTS` that emits
fixed-size PCM chunks. The live path is opt-in via
``RUN_ELEVENLABS_BENCH=1``.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from config.settings import settings
from modules.tts.elevenlabs_client import ElevenLabsTTS
from tests._support.benchmark import elevenlabs_enabled, measure_async
from tests._support.fakes import FakeElevenLabsTTS


pytestmark = pytest.mark.latency


FAKE_ITERS = int(os.environ.get("BENCH_ELEVENLABS_FAKE_ITERATIONS", "20"))
LIVE_ITERS = int(os.environ.get("BENCH_ELEVENLABS_LIVE_ITERATIONS", "3"))


_TEXT = "Thanks for picking up — do you have a quick minute to chat?"


def test_latency_elevenlabs_stream_pcm_with_fake():
    fake = FakeElevenLabsTTS()

    async def go() -> None:
        for _ in range(FAKE_ITERS):
            async with measure_async(
                "elevenlabs_tts",
                "stream_pcm (fake)",
                metadata={"mode": "fake"},
            ):
                async for _chunk in fake.stream_pcm(_TEXT):
                    pass

    asyncio.run(go())


def test_latency_elevenlabs_ttfb_with_fake():
    """Measures the first-chunk arrival time only (TTFB-equivalent)."""

    fake = FakeElevenLabsTTS()

    async def go() -> None:
        for _ in range(FAKE_ITERS):
            async with measure_async(
                "elevenlabs_tts",
                "stream_pcm TTFB (fake)",
                metadata={"mode": "fake"},
            ):
                async for _chunk in fake.stream_pcm(_TEXT):
                    break

    asyncio.run(go())


@pytest.mark.external
@pytest.mark.skipif(
    not (elevenlabs_enabled() and settings.ELEVENLABS_API_KEY),
    reason="ElevenLabs benchmark disabled (set RUN_ELEVENLABS_BENCH=1)",
)
def test_latency_elevenlabs_stream_pcm_live():
    async def go() -> None:
        client = ElevenLabsTTS()
        for _ in range(LIVE_ITERS):
            async with measure_async(
                "elevenlabs_tts",
                "stream_pcm (live)",
                metadata={"mode": "live", "voice": client.default_voice_id},
            ):
                async for _chunk in client.stream_pcm(_TEXT):
                    pass

    asyncio.run(go())


@pytest.mark.external
@pytest.mark.skipif(
    not (elevenlabs_enabled() and settings.ELEVENLABS_API_KEY),
    reason="ElevenLabs benchmark disabled (set RUN_ELEVENLABS_BENCH=1)",
)
def test_latency_elevenlabs_ttfb_live():
    async def go() -> None:
        client = ElevenLabsTTS()
        for _ in range(LIVE_ITERS):
            async with measure_async(
                "elevenlabs_tts",
                "stream_pcm TTFB (live)",
                metadata={"mode": "live", "voice": client.default_voice_id},
            ):
                async for _chunk in client.stream_pcm(_TEXT):
                    break

    asyncio.run(go())
