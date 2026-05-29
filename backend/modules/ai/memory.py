"""Redis-backed conversation memory.

Each call_id owns three keys in Redis:

* ``ai:mem:{call_id}:history``  — JSON list of :class:`ChatMessage`
  (rolling window, capped at ``settings.AI_MEMORY_MAX_TURNS``).
* ``ai:mem:{call_id}:meta``     — JSON dict with call-level metadata
  (organization id, persona, extra_context).
* ``ai:mem:{call_id}:qual``     — JSON-encoded :class:`QualificationState`.

All three share a single TTL (``settings.AI_MEMORY_TTL_SECONDS``) so a
forgotten call evicts cleanly without us tracking it.

We use ``redis.asyncio`` so the memory ops can be awaited from the same
event loop as the OpenAI client and the LiveKit transports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from redis import asyncio as aioredis

from common.logging import get_logger
from config.settings import settings
from modules.ai.exceptions import AIMemoryError
from modules.ai.qualification import (
    QualificationFramework,
    QualificationState,
    QualificationTracker,
)
from modules.ai.schema import ChatMessage, MessageRole

log = get_logger("ai.memory")


_HISTORY_FIELD = "history"
_META_FIELD = "meta"
_QUAL_FIELD = "qual"


def _key(call_id: str, field: str) -> str:
    return f"ai:mem:{call_id}:{field}"


# ---------------------------------------------------------------------------
# Snapshot DTO
# ---------------------------------------------------------------------------


@dataclass
class CallMemorySnapshot:
    """All persisted state for one call, materialised in one round-trip."""

    call_id: str
    history: list[ChatMessage]
    meta: dict[str, Any]
    qualification: QualificationState


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


class ConversationMemory:
    """Async Redis facade for per-call conversational state."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        max_turns: int | None = None,
        ttl_seconds: int | None = None,
        client: aioredis.Redis | None = None,
    ) -> None:
        self._redis_url = redis_url or settings.REDIS_URL
        self._max_messages = (max_turns or settings.AI_MEMORY_MAX_TURNS) * 2
        self._ttl = ttl_seconds or settings.AI_MEMORY_TTL_SECONDS
        # ``decode_responses=True`` so we get str back, not bytes — every
        # value in this module is JSON.
        self._r: aioredis.Redis = client or aioredis.from_url(
            self._redis_url, decode_responses=True
        )

    @property
    def max_messages(self) -> int:
        return self._max_messages

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        try:
            await self._r.aclose()
        except Exception:  # pragma: no cover
            log.exception("ai.memory.close_failed")

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def append_message(self, call_id: str, message: ChatMessage) -> None:
        """Append a message and trim to the rolling window."""

        if message.ts is None:
            message = message.model_copy(update={"ts": datetime.now(timezone.utc)})

        try:
            pipe = self._r.pipeline(transaction=True)
            pipe.rpush(_key(call_id, _HISTORY_FIELD), message.model_dump_json())
            pipe.ltrim(
                _key(call_id, _HISTORY_FIELD),
                -self._max_messages,
                -1,
            )
            pipe.expire(_key(call_id, _HISTORY_FIELD), self._ttl)
            await pipe.execute()
        except Exception as exc:
            log.exception("ai.memory.append_failed", call_id=call_id)
            raise AIMemoryError(f"redis append failed: {exc}") from exc

    async def get_history(self, call_id: str) -> list[ChatMessage]:
        try:
            raw = await self._r.lrange(_key(call_id, _HISTORY_FIELD), 0, -1)
        except Exception as exc:
            log.exception("ai.memory.history_failed", call_id=call_id)
            raise AIMemoryError(f"redis history fetch failed: {exc}") from exc

        out: list[ChatMessage] = []
        for blob in raw:
            try:
                out.append(ChatMessage.model_validate_json(blob))
            except Exception:
                log.warning("ai.memory.skip_corrupt_message", call_id=call_id)
        return out

    async def clear_history(self, call_id: str) -> None:
        try:
            await self._r.delete(_key(call_id, _HISTORY_FIELD))
        except Exception as exc:
            log.exception("ai.memory.clear_failed", call_id=call_id)
            raise AIMemoryError(f"redis clear failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    async def set_meta(self, call_id: str, meta: dict[str, Any]) -> None:
        try:
            await self._r.set(
                _key(call_id, _META_FIELD),
                json.dumps(meta, default=str),
                ex=self._ttl,
            )
        except Exception as exc:
            log.exception("ai.memory.meta_set_failed", call_id=call_id)
            raise AIMemoryError(f"redis meta set failed: {exc}") from exc

    async def get_meta(self, call_id: str) -> dict[str, Any]:
        try:
            blob = await self._r.get(_key(call_id, _META_FIELD))
        except Exception as exc:
            log.exception("ai.memory.meta_get_failed", call_id=call_id)
            raise AIMemoryError(f"redis meta get failed: {exc}") from exc
        if not blob:
            return {}
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            log.warning("ai.memory.meta_corrupt", call_id=call_id)
            return {}

    # ------------------------------------------------------------------
    # Qualification
    # ------------------------------------------------------------------

    async def get_qualification(
        self,
        call_id: str,
        *,
        framework: QualificationFramework | str | None = None,
    ) -> QualificationState:
        try:
            blob = await self._r.get(_key(call_id, _QUAL_FIELD))
        except Exception as exc:
            log.exception("ai.memory.qual_get_failed", call_id=call_id)
            raise AIMemoryError(f"redis qual get failed: {exc}") from exc
        if blob:
            try:
                return QualificationState.from_json(blob)
            except Exception:
                log.warning("ai.memory.qual_corrupt", call_id=call_id)
        return QualificationTracker.empty(framework)

    async def save_qualification(
        self, call_id: str, state: QualificationState
    ) -> None:
        try:
            await self._r.set(
                _key(call_id, _QUAL_FIELD),
                state.to_json(),
                ex=self._ttl,
            )
        except Exception as exc:
            log.exception("ai.memory.qual_set_failed", call_id=call_id)
            raise AIMemoryError(f"redis qual set failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Combined snapshot
    # ------------------------------------------------------------------

    async def snapshot(
        self,
        call_id: str,
        *,
        framework: QualificationFramework | str | None = None,
    ) -> CallMemorySnapshot:
        """Fetch history + meta + qualification in one pipeline."""

        try:
            pipe = self._r.pipeline(transaction=False)
            pipe.lrange(_key(call_id, _HISTORY_FIELD), 0, -1)
            pipe.get(_key(call_id, _META_FIELD))
            pipe.get(_key(call_id, _QUAL_FIELD))
            raw_history, raw_meta, raw_qual = await pipe.execute()
        except Exception as exc:
            log.exception("ai.memory.snapshot_failed", call_id=call_id)
            raise AIMemoryError(f"redis snapshot failed: {exc}") from exc

        history: list[ChatMessage] = []
        for blob in raw_history or []:
            try:
                history.append(ChatMessage.model_validate_json(blob))
            except Exception:
                continue

        meta: dict[str, Any] = {}
        if raw_meta:
            try:
                meta = json.loads(raw_meta)
            except json.JSONDecodeError:
                meta = {}

        if raw_qual:
            try:
                qual = QualificationState.from_json(raw_qual)
            except Exception:
                qual = QualificationTracker.empty(framework)
        else:
            qual = QualificationTracker.empty(framework)

        return CallMemorySnapshot(
            call_id=call_id,
            history=history,
            meta=meta,
            qualification=qual,
        )

    # ------------------------------------------------------------------
    # Convenience writers
    # ------------------------------------------------------------------

    async def record_user_turn(self, call_id: str, text: str) -> None:
        await self.append_message(
            call_id,
            ChatMessage(role=MessageRole.USER, content=text),
        )

    async def record_assistant_turn(
        self,
        call_id: str,
        text: str,
        *,
        tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.append_message(
            call_id,
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=text,
                tokens=tokens,
                metadata=metadata,
            ),
        )
