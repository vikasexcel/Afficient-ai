"""FastAPI dependencies for the AI module.

Process-wide singletons for the OpenAI client, the Redis-backed memory,
and the high-level :class:`AIService`. ``shutdown_ai`` is invoked from
the main lifespan handler so the HTTP/Redis connections are released
cleanly on process exit.

Dependency providers translate :class:`AIError` (e.g. missing API key)
into :class:`fastapi.HTTPException` so misconfiguration surfaces as a
readable JSON error rather than a generic 500.
"""

from __future__ import annotations

from fastapi import HTTPException

from modules.ai.exceptions import AIError
from modules.ai.memory import ConversationMemory
from modules.ai.openai_client import OpenAIClient
from modules.ai.service import AIService

_openai: OpenAIClient | None = None
_memory: ConversationMemory | None = None
_service: AIService | None = None


def get_openai() -> OpenAIClient:
    global _openai
    if _openai is None:
        try:
            _openai = OpenAIClient()
        except AIError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _openai


def get_memory() -> ConversationMemory:
    global _memory
    if _memory is None:
        try:
            _memory = ConversationMemory()
        except AIError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _memory


def get_ai_service() -> AIService:
    global _service
    if _service is None:
        try:
            _service = AIService(openai=get_openai(), memory=get_memory())
        except AIError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _service


async def shutdown_ai() -> None:
    """Release the OpenAI HTTP client + Redis pool."""

    global _openai, _memory, _service
    if _openai is not None:
        await _openai.aclose()
        _openai = None
    if _memory is not None:
        await _memory.aclose()
        _memory = None
    _service = None


def reset_ai_singletons() -> None:
    """Test helper — wipe singletons without closing them."""

    global _openai, _memory, _service
    _openai = None
    _memory = None
    _service = None
