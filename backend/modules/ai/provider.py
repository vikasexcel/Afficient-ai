"""Backwards-compatible provider shim.

The pre-existing :class:`AIProvider` returned a hardcoded string. We keep
the class name + ``generate(prompt)`` signature so anything that imported
it continues to work, but the implementation now calls GPT-4o via the
shared :class:`OpenAIClient` singleton.

For anything new, prefer :class:`modules.ai.service.AIService` (stateful)
or :class:`modules.ai.openai_client.OpenAIClient` (stateless) directly —
both expose richer return types and proper async semantics.
"""

from __future__ import annotations

from modules.ai.exceptions import AIError
from modules.ai.openai_client import OpenAIClient
from modules.ai.schema import ChatMessage, MessageRole


class AIProvider:
    """Thin sync facade preserved for legacy callers."""

    _client: OpenAIClient | None = None

    @classmethod
    def _get_client(cls) -> OpenAIClient:
        if cls._client is None:
            cls._client = OpenAIClient()
        return cls._client

    @classmethod
    async def agenerate(
        cls,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Async one-shot completion. Returns a dict matching the legacy shape.

        Extra keys (``model``, ``prompt_tokens`` etc.) are additive and
        won't break callers that only read ``output``.
        """

        messages: list[ChatMessage] = []
        if system:
            messages.append(ChatMessage(role=MessageRole.SYSTEM, content=system))
        messages.append(ChatMessage(role=MessageRole.USER, content=prompt))

        try:
            result = await cls._get_client().complete(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except AIError as exc:
            return {
                "output": "",
                "error": exc.message,
                "status_code": exc.status_code,
            }

        return {
            "output": result.text,
            "model": result.stats.model,
            "prompt_tokens": result.stats.prompt_tokens,
            "completion_tokens": result.stats.completion_tokens,
            "total_tokens": result.stats.total_tokens,
            "latency_ms": result.stats.latency_ms,
            "finish_reason": result.stats.finish_reason,
        }

    # ------------------------------------------------------------------
    # Legacy sync helper kept for callers that aren't async-aware.
    # ------------------------------------------------------------------

    @classmethod
    def generate(cls, prompt: str) -> dict:
        """Synchronous wrapper that runs the async call in a fresh loop.

        Do NOT call this from inside an async context — use :meth:`agenerate`.
        """

        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(cls.agenerate(prompt))

        raise RuntimeError(
            "AIProvider.generate(prompt) is sync-only; call AIProvider.agenerate "
            "from async code instead."
        )
