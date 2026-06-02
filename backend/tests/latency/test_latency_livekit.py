"""Latency benchmarks for LiveKit token + (optional) room operations.

Token minting is always benchmarked — it's pure JWT, no network. Room
operations only run when ``RUN_LIVEKIT_BENCH=1`` is set in the env, so
the suite stays fast and hermetic by default.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from config.settings import settings
from modules.livekit.schema import CreateRoomRequest, TokenRequest
from modules.livekit.service import LiveKitService
from tests._support.benchmark import livekit_enabled, measure, measure_async


pytestmark = pytest.mark.latency


TOKEN_ITERS = int(os.environ.get("BENCH_LIVEKIT_TOKEN_ITERATIONS", "100"))
ROOM_ITERS = int(os.environ.get("BENCH_LIVEKIT_ROOM_ITERATIONS", "5"))


def _local_svc() -> LiveKitService:
    """Offline service with dummy credentials — only safe for token minting."""

    return LiveKitService(
        url="wss://aifficient.test",
        api_key="APItest1234",
        api_secret="0123456789abcdefghijklmnopqrstuv",
    )


def test_latency_livekit_token_mint():
    svc = _local_svc()
    req = TokenRequest(room="bench-room", identity="bench-user")
    for _ in range(TOKEN_ITERS):
        with measure("livekit", "generate_token"):
            svc.generate_token(req)


@pytest.mark.skipif(
    not livekit_enabled() or not (
        settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET
    ),
    reason="LiveKit benchmarks disabled (set RUN_LIVEKIT_BENCH=1)",
)
def test_latency_livekit_room_create_and_delete():
    """Real LiveKit room create/list/delete cycle. Opt-in."""

    async def go() -> None:
        svc = LiveKitService()
        try:
            for _ in range(ROOM_ITERS):
                name = f"bench-{uuid.uuid4().hex[:8]}"
                async with measure_async("livekit", "create_room"):
                    await svc.create_room(
                        CreateRoomRequest(
                            name=name,
                            empty_timeout=30,
                            max_participants=2,
                        )
                    )
                async with measure_async("livekit", "list_rooms[1]"):
                    await svc.list_rooms(names=[name])
                async with measure_async("livekit", "delete_room"):
                    await svc.delete_room(name)
        finally:
            await svc.aclose()

    asyncio.run(go())


@pytest.mark.skipif(
    not livekit_enabled() or not (
        settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET
    ),
    reason="LiveKit benchmarks disabled (set RUN_LIVEKIT_BENCH=1)",
)
def test_latency_livekit_connection_warmup():
    """Wraps ``LiveKitService._get_client`` so the first connection cost
    is captured separately from steady-state RPC latency."""

    async def go() -> None:
        svc = LiveKitService()
        try:
            async with measure_async("livekit", "client_first_connect"):
                await svc._get_client()  # noqa: SLF001 — explicit warmup
            # Steady-state RPC.
            for _ in range(5):
                async with measure_async("livekit", "list_rooms[steady]"):
                    await svc.list_rooms()
        finally:
            await svc.aclose()

    asyncio.run(go())
