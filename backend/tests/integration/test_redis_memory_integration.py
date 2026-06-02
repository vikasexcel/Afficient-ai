"""Integration tests for ``ConversationMemory`` against live Redis.

Skipped automatically when Redis isn't reachable on the configured port.
"""

from __future__ import annotations

import uuid

import pytest
import redis

from config.settings import settings
from modules.ai.memory import ConversationMemory
from modules.ai.qualification import QualificationFramework
from modules.ai.schema import ChatMessage, MessageRole


def _redis_available() -> bool:
    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        return bool(r.ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable"),
]


@pytest.fixture
def memory() -> ConversationMemory:
    return ConversationMemory()


@pytest.fixture
def call_id() -> str:
    return f"pytest-{uuid.uuid4().hex[:10]}"


async def test_append_and_get_history_round_trip(memory: ConversationMemory, call_id: str):
    await memory.record_user_turn(call_id, "hello")
    await memory.record_assistant_turn(call_id, "hi there")
    history = await memory.get_history(call_id)
    assert [m.role for m in history] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert [m.content for m in history] == ["hello", "hi there"]
    await memory.clear_history(call_id)


async def test_meta_round_trip(memory: ConversationMemory, call_id: str):
    payload = {"persona": "outbound_sdr", "framework": "BANT", "extra": {"k": "v"}}
    await memory.set_meta(call_id, payload)
    got = await memory.get_meta(call_id)
    assert got["persona"] == "outbound_sdr"
    assert got["extra"] == {"k": "v"}


async def test_snapshot_returns_all_three_pieces(
    memory: ConversationMemory, call_id: str
):
    await memory.set_meta(call_id, {"persona": "outbound_sdr"})
    await memory.record_user_turn(call_id, "budget $50k")
    snap = await memory.snapshot(call_id, framework=QualificationFramework.BANT)
    assert snap.call_id == call_id
    assert len(snap.history) == 1
    assert snap.meta["persona"] == "outbound_sdr"
    assert snap.qualification.framework == QualificationFramework.BANT


async def test_history_capped_to_max_messages(
    memory: ConversationMemory, call_id: str
):
    cap = memory.max_messages
    for i in range(cap + 4):
        await memory.append_message(
            call_id, ChatMessage(role=MessageRole.USER, content=f"msg-{i}")
        )
    history = await memory.get_history(call_id)
    assert len(history) == cap
    # The window slides forwards, so the latest one survives.
    assert history[-1].content == f"msg-{cap + 3}"
    await memory.clear_history(call_id)


async def test_clear_history_drops_only_history(
    memory: ConversationMemory, call_id: str
):
    await memory.set_meta(call_id, {"k": "v"})
    await memory.record_user_turn(call_id, "hi")
    await memory.clear_history(call_id)
    assert await memory.get_history(call_id) == []
    # Meta survives by design — only the history list is dropped.
    assert (await memory.get_meta(call_id))["k"] == "v"
