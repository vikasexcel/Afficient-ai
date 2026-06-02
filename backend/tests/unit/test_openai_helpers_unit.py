"""Unit tests for stateless OpenAI-client helpers (no network)."""

from __future__ import annotations

import pytest

from modules.ai.openai_client import _to_openai_messages, build_messages
from modules.ai.schema import ChatMessage, MessageRole


pytestmark = pytest.mark.unit


def test_to_openai_messages_serialises_roles_as_strings():
    out = _to_openai_messages(
        [
            ChatMessage(role=MessageRole.SYSTEM, content="sys"),
            ChatMessage(role=MessageRole.USER, content="hi"),
            ChatMessage(role=MessageRole.ASSISTANT, content="hello"),
        ]
    )
    assert [m["role"] for m in out] == ["system", "user", "assistant"]
    assert [m["content"] for m in out] == ["sys", "hi", "hello"]


def test_build_messages_prepends_system_and_appends_user_input():
    history = [
        ChatMessage(role=MessageRole.USER, content="earlier"),
        ChatMessage(role=MessageRole.ASSISTANT, content="reply"),
    ]
    msgs = build_messages(system="rules", history=history, user_input="hi")
    assert msgs[0].role == MessageRole.SYSTEM
    assert msgs[0].content == "rules"
    assert msgs[-1].role == MessageRole.USER
    assert msgs[-1].content == "hi"
    assert len(msgs) == 4


def test_build_messages_without_user_input_only_returns_system_plus_history():
    msgs = build_messages(system="rules")
    assert len(msgs) == 1
    assert msgs[0].role == MessageRole.SYSTEM
