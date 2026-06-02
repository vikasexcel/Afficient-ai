"""Latency benchmarks for the OpenAI / GPT path.

Two flavours:

* **Hermetic** — exercises the orchestrator path through a
  :class:`FakeOpenAIClient` so we get an apples-to-apples comparison of
  the framework overhead vs. provider latency.
* **Live** — opt-in via ``RUN_OPENAI_BENCH=1``; calls the real
  ``OpenAI`` chat completion API with the configured key. The fake-path
  numbers stay in the report so consumers can subtract them.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from config.settings import settings
from modules.ai.openai_client import OpenAIClient
from modules.ai.schema import ChatMessage, MessageRole
from tests._support.benchmark import measure_async, openai_enabled
from tests._support.fakes import FakeOpenAIClient


pytestmark = pytest.mark.latency


FAKE_ITERS = int(os.environ.get("BENCH_OPENAI_FAKE_ITERATIONS", "20"))
LIVE_ITERS = int(os.environ.get("BENCH_OPENAI_LIVE_ITERATIONS", "3"))


_MESSAGES = [
    ChatMessage(role=MessageRole.SYSTEM, content="You are a brief assistant."),
    ChatMessage(role=MessageRole.USER, content="Suggest two meeting slots tomorrow."),
]


def test_latency_openai_complete_with_fake():
    fake = FakeOpenAIClient(per_call_latency_ms=10)

    async def go() -> None:
        for _ in range(FAKE_ITERS):
            async with measure_async(
                "openai_gpt",
                "complete (fake)",
                metadata={"mode": "fake"},
            ):
                await fake.complete(_MESSAGES)

    asyncio.run(go())


def test_latency_openai_stream_collected_with_fake():
    fake = FakeOpenAIClient(per_call_latency_ms=10)

    async def go() -> None:
        for _ in range(FAKE_ITERS):
            async with measure_async(
                "openai_gpt",
                "stream_collected (fake)",
                metadata={"mode": "fake"},
            ):
                await fake.stream_collected(_MESSAGES)

    asyncio.run(go())


@pytest.mark.external
@pytest.mark.skipif(
    not (openai_enabled() and settings.OPENAI_API_KEY),
    reason="OpenAI benchmark disabled (set RUN_OPENAI_BENCH=1 and OPENAI_API_KEY)",
)
def test_latency_openai_complete_live():
    async def go() -> None:
        client = OpenAIClient()
        try:
            for _ in range(LIVE_ITERS):
                async with measure_async(
                    "openai_gpt",
                    "complete (live)",
                    metadata={"mode": "live", "model": client.model},
                ):
                    await client.complete(_MESSAGES, max_tokens=64)
        finally:
            await client.aclose()

    asyncio.run(go())


@pytest.mark.external
@pytest.mark.skipif(
    not (openai_enabled() and settings.OPENAI_API_KEY),
    reason="OpenAI benchmark disabled (set RUN_OPENAI_BENCH=1)",
)
def test_latency_openai_stream_collected_live():
    async def go() -> None:
        client = OpenAIClient()
        try:
            for _ in range(LIVE_ITERS):
                async with measure_async(
                    "openai_gpt",
                    "stream_collected (live)",
                    metadata={"mode": "live", "model": client.model},
                ):
                    await client.stream_collected(_MESSAGES, max_tokens=64)
        finally:
            await client.aclose()

    asyncio.run(go())
