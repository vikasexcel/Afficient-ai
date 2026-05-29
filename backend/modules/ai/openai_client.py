"""Async OpenAI client used by the conversation engine.

Wraps the official ``openai`` Python SDK and exposes two primitives:

* :meth:`OpenAIClient.complete` — one-shot, non-streaming. Useful for
  end-of-call summaries and qualification scoring where we want the whole
  blob back before doing anything with it.
* :meth:`OpenAIClient.stream` — async iterator of token chunks. The
  conversation orchestrator uses this so it can start feeding text to
  ElevenLabs the moment GPT-4o emits the first sentence boundary, which
  is the lowest-latency path for voice.

Both methods translate provider errors into the :mod:`modules.ai.exceptions`
hierarchy so the HTTP layer and the orchestrator can react uniformly.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Sequence

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from common.logging import get_logger
from config.settings import settings
from modules.ai.exceptions import (
    AIConfigError,
    AIProviderError,
    AIQuotaError,
    AIRateLimitError,
    AITimeoutError,
)
from modules.ai.schema import ChatMessage, ChatTurnResult, ChatTurnStats, MessageRole

log = get_logger("ai.openai")


# ---------------------------------------------------------------------------
# Stream chunk DTO
# ---------------------------------------------------------------------------


@dataclass
class StreamChunk:
    """One token-batch from a streaming completion."""

    delta: str
    is_first: bool = False
    is_final: bool = False
    finish_reason: str | None = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _to_openai_messages(
    messages: Sequence[ChatMessage],
) -> list[dict[str, str]]:
    """Translate our :class:`ChatMessage` records to the OpenAI wire format."""

    out: list[dict[str, str]] = []
    for m in messages:
        role = m.role.value if isinstance(m.role, MessageRole) else str(m.role)
        out.append({"role": role, "content": m.content})
    return out


class OpenAIClient:
    """Thin async wrapper around :class:`openai.AsyncOpenAI`.

    One client instance per process is plenty — the SDK already pools
    connections via ``httpx``. The :func:`modules.ai.dependencies.get_openai`
    helper enforces that.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        key = api_key or settings.OPENAI_API_KEY
        if not key:
            raise AIConfigError("OPENAI_API_KEY is not set")

        self._model = model or settings.OPENAI_MODEL
        self._temperature = (
            temperature if temperature is not None else settings.OPENAI_TEMPERATURE
        )
        self._max_tokens = max_tokens or settings.OPENAI_MAX_TOKENS
        self._timeout = timeout if timeout is not None else settings.OPENAI_TIMEOUT_SECONDS
        self._max_retries = (
            max_retries if max_retries is not None else settings.OPENAI_MAX_RETRIES
        )

        self._client = AsyncOpenAI(
            api_key=key,
            base_url=base_url or settings.OPENAI_BASE_URL or None,
            organization=organization or settings.OPENAI_ORG_ID or None,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    @property
    def default_temperature(self) -> float:
        return self._temperature

    @property
    def default_max_tokens(self) -> int:
        return self._max_tokens

    # ------------------------------------------------------------------
    # One-shot completion
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        user: str | None = None,
    ) -> ChatTurnResult:
        """Block until the LLM returns a full reply."""

        mdl = model or self._model
        t0 = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(
                model=mdl,
                messages=_to_openai_messages(messages),
                temperature=temperature if temperature is not None else self._temperature,
                max_tokens=max_tokens or self._max_tokens,
                user=user,
                stream=False,
            )
        except Exception as exc:
            self._raise_translated(exc, mdl)
            raise  # pragma: no cover — _raise_translated never returns

        latency_ms = int((time.perf_counter() - t0) * 1000)

        choice = resp.choices[0]
        usage = resp.usage
        text = (choice.message.content or "").strip()

        stats = ChatTurnStats(
            latency_ms=latency_ms,
            ttft_ms=latency_ms,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
            finish_reason=choice.finish_reason,
            model=resp.model or mdl,
        )

        log.info(
            "ai.complete.done",
            model=stats.model,
            latency_ms=latency_ms,
            prompt_tokens=stats.prompt_tokens,
            completion_tokens=stats.completion_tokens,
            finish_reason=stats.finish_reason,
        )
        return ChatTurnResult(text=text, stats=stats)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        user: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Yield :class:`StreamChunk` instances as tokens arrive.

        The final chunk has ``is_final=True`` and ``finish_reason`` set.
        We request usage info via ``stream_options={"include_usage": True}``
        so :meth:`stream_collected` can populate token counts.
        """

        mdl = model or self._model
        t0 = time.perf_counter()
        first_token_time: float | None = None
        try:
            stream = await self._client.chat.completions.create(
                model=mdl,
                messages=_to_openai_messages(messages),
                temperature=temperature if temperature is not None else self._temperature,
                max_tokens=max_tokens or self._max_tokens,
                user=user,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as exc:
            self._raise_translated(exc, mdl)
            raise  # pragma: no cover

        produced_any = False
        finish_reason: str | None = None
        try:
            async for event in stream:
                if not event.choices:
                    # The terminal usage-only event has empty choices.
                    continue
                choice = event.choices[0]
                delta = (choice.delta.content or "") if choice.delta else ""
                if delta:
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                    yield StreamChunk(
                        delta=delta,
                        is_first=not produced_any,
                        is_final=False,
                        finish_reason=None,
                    )
                    produced_any = True
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except Exception as exc:
            self._raise_translated(exc, mdl)
            raise  # pragma: no cover

        latency_ms = int((time.perf_counter() - t0) * 1000)
        ttft_ms = (
            int((first_token_time - t0) * 1000) if first_token_time else latency_ms
        )
        yield StreamChunk(
            delta="",
            is_first=False,
            is_final=True,
            finish_reason=finish_reason or "stop",
        )
        log.info(
            "ai.stream.done",
            model=mdl,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            finish_reason=finish_reason,
        )

    async def stream_collected(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        user: str | None = None,
        on_first_token: "asyncio.Event | None" = None,
    ) -> ChatTurnResult:
        """Convenience: collect the whole streamed reply into a single string.

        ``on_first_token`` is set as soon as the first non-empty chunk
        arrives — handy for orchestrators that want to fire TTS warmup or
        cancel timers.
        """

        mdl = model or self._model
        t0 = time.perf_counter()
        first_token_time: float | None = None
        buf: list[str] = []
        finish_reason: str | None = None

        try:
            stream = await self._client.chat.completions.create(
                model=mdl,
                messages=_to_openai_messages(messages),
                temperature=temperature if temperature is not None else self._temperature,
                max_tokens=max_tokens or self._max_tokens,
                user=user,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as exc:
            self._raise_translated(exc, mdl)
            raise  # pragma: no cover

        usage_prompt = 0
        usage_completion = 0
        usage_total = 0

        try:
            async for event in stream:
                if event.usage is not None:
                    usage_prompt = event.usage.prompt_tokens or 0
                    usage_completion = event.usage.completion_tokens or 0
                    usage_total = event.usage.total_tokens or 0
                if not event.choices:
                    continue
                choice = event.choices[0]
                delta = (choice.delta.content or "") if choice.delta else ""
                if delta:
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                        if on_first_token is not None and not on_first_token.is_set():
                            on_first_token.set()
                    buf.append(delta)
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except Exception as exc:
            self._raise_translated(exc, mdl)
            raise  # pragma: no cover

        latency_ms = int((time.perf_counter() - t0) * 1000)
        ttft_ms = (
            int((first_token_time - t0) * 1000) if first_token_time else latency_ms
        )
        text = "".join(buf).strip()

        stats = ChatTurnStats(
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            prompt_tokens=usage_prompt,
            completion_tokens=usage_completion,
            total_tokens=usage_total,
            finish_reason=finish_reason or "stop",
            model=mdl,
        )
        log.info(
            "ai.stream_collected.done",
            model=mdl,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            prompt_tokens=usage_prompt,
            completion_tokens=usage_completion,
            finish_reason=finish_reason,
        )
        return ChatTurnResult(text=text, stats=stats)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        try:
            await self._client.close()
        except Exception:  # pragma: no cover - defensive
            log.exception("ai.openai.close_failed")

    # ------------------------------------------------------------------
    # Error translation
    # ------------------------------------------------------------------

    @staticmethod
    def _raise_translated(exc: Exception, model: str) -> None:
        # Order matters: more specific subclasses first.
        if isinstance(exc, APITimeoutError):
            raise AITimeoutError(f"OpenAI timeout for model={model}") from exc
        if isinstance(exc, RateLimitError):
            raise AIRateLimitError(f"OpenAI rate limited model={model}") from exc
        if isinstance(exc, AuthenticationError):
            raise AIConfigError("OpenAI authentication failed") from exc
        if isinstance(exc, APIStatusError):
            status = getattr(exc, "status_code", None) or 502
            if status == 429:
                raise AIRateLimitError("OpenAI rate limited") from exc
            if status in (402, 403) and "quota" in str(exc).lower():
                raise AIQuotaError(str(exc)) from exc
            raise AIProviderError(
                f"OpenAI status={status}: {exc}",
                status_code=502,
            ) from exc
        if isinstance(exc, APIConnectionError):
            raise AIProviderError(f"OpenAI connection error: {exc}") from exc
        # Unknown — surface as a 502 so callers don't see a 500.
        raise AIProviderError(f"OpenAI unexpected error: {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_messages(
    *,
    system: str,
    history: Iterable[ChatMessage] = (),
    user_input: str | None = None,
) -> list[ChatMessage]:
    """Compose the message list sent to OpenAI for one turn.

    Order is always: ``[system, *history, user_input]``. ``history``
    should already exclude the system message (it's prepended fresh each
    turn so persona/context changes take effect immediately).
    """

    msgs: list[ChatMessage] = [
        ChatMessage(role=MessageRole.SYSTEM, content=system)
    ]
    msgs.extend(history)
    if user_input:
        msgs.append(ChatMessage(role=MessageRole.USER, content=user_input))
    return msgs
