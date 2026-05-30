"""Interruption (barge-in) event recording.

Each barge-in is captured both as an in-process metric on
:class:`OrchestratorStats` and as a structured event in Redis under
``ai:interruptions:{call_id}`` (FIFO, capped by
``settings.BARGE_IN_MAX_EVENTS_PER_CALL``).

Storing per-event records — not just an aggregate count — lets the
analytics dashboard answer questions like:

* how often did the lead interrupt the agent's *opening line*?
* what was the median agent-silence latency across all barge-ins?
* which carriers exhibit slow VAD (high ``trigger_latency_ms``)?
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from common.logging import get_logger
from config.settings import settings
from modules.ai.exceptions import AIMemoryError
from modules.ai.memory import ConversationMemory

log = get_logger("ai.interruption")


def _events_key(call_id: str) -> str:
    return f"ai:interruptions:{call_id}"


def _metrics_key(call_id: str) -> str:
    return f"ai:metrics:{call_id}"


@dataclass
class InterruptionEvent:
    """One barge-in. Persisted to Redis and surfaced in metrics dumps.

    ``trigger_latency_ms`` is how long it took from the STT event arriving
    in our process to the TTS being told to stop. ``silence_latency_ms``
    is how long after we asked TTS to stop did it actually go silent
    (i.e. the audio buffer was cleared and the pump task ended). The
    end-to-end "how late was the agent" experienced by the lead is the
    sum of these plus the STT VAD detection latency upstream.
    """

    call_id: str
    ts_unix: float
    stt_event_ts_ms: int  # offset since STT session start (Deepgram clock)
    trigger_latency_ms: int
    silence_latency_ms: int
    source: str  # "speech_started" | "partial"
    state_before: str
    partial_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, blob: str) -> "InterruptionEvent":
        return cls(**json.loads(blob))


@dataclass
class InterruptionMetrics:
    """In-process aggregate counters surfaced on the orchestrator.

    These are the source of truth for the ``barge_in_*`` fields in
    :class:`OrchestratorStats`. Kept in their own dataclass so the
    orchestrator can ``replace`` or ``reset`` them in tests without
    touching unrelated counters.
    """

    total: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    trigger_latency_ms_total: int = 0
    silence_latency_ms_total: int = 0
    cooldown_skipped: int = 0
    last_event_ts: float | None = None

    @property
    def avg_trigger_latency_ms(self) -> float:
        return self.trigger_latency_ms_total / self.total if self.total else 0.0

    @property
    def avg_silence_latency_ms(self) -> float:
        return self.silence_latency_ms_total / self.total if self.total else 0.0

    def record(self, event: InterruptionEvent) -> None:
        self.total += 1
        self.by_source[event.source] = self.by_source.get(event.source, 0) + 1
        self.trigger_latency_ms_total += event.trigger_latency_ms
        self.silence_latency_ms_total += event.silence_latency_ms
        self.last_event_ts = event.ts_unix

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_source": dict(self.by_source),
            "avg_trigger_latency_ms": round(self.avg_trigger_latency_ms, 2),
            "avg_silence_latency_ms": round(self.avg_silence_latency_ms, 2),
            "cooldown_skipped": self.cooldown_skipped,
            "last_event_ts": self.last_event_ts,
        }


class InterruptionLog:
    """Redis-backed FIFO of :class:`InterruptionEvent` records per call."""

    def __init__(self, memory: ConversationMemory) -> None:
        self._memory = memory
        self._max = settings.BARGE_IN_MAX_EVENTS_PER_CALL

    async def record(self, event: InterruptionEvent) -> None:
        """Append an event and trim the list to the configured window."""

        try:
            pipe = self._memory._r.pipeline(transaction=True)  # noqa: SLF001
            pipe.rpush(_events_key(event.call_id), event.to_json())
            pipe.ltrim(_events_key(event.call_id), -self._max, -1)
            pipe.expire(_events_key(event.call_id), self._memory.ttl_seconds)
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            # Interruption logging is best-effort; never fail the call
            # because Redis blipped.
            log.warning(
                "ai.interruption.record_failed",
                call_id=event.call_id,
                error=str(exc),
            )

    async def list_for_call(self, call_id: str) -> list[InterruptionEvent]:
        try:
            raw = await self._memory._r.lrange(  # noqa: SLF001
                _events_key(call_id), 0, -1
            )
        except Exception as exc:
            raise AIMemoryError(f"redis interruption fetch failed: {exc}") from exc
        out: list[InterruptionEvent] = []
        for blob in raw:
            try:
                out.append(InterruptionEvent.from_json(blob))
            except Exception:
                continue
        return out

    async def clear(self, call_id: str) -> None:
        try:
            await self._memory._r.delete(_events_key(call_id))  # noqa: SLF001
        except Exception:  # noqa: BLE001 — best effort
            log.warning("ai.interruption.clear_failed", call_id=call_id)


# ---------------------------------------------------------------------------
# Live metrics snapshot (Redis) — for cross-process dashboards
# ---------------------------------------------------------------------------


async def publish_metrics_snapshot(
    memory: ConversationMemory,
    *,
    call_id: str,
    payload: dict[str, Any],
) -> None:
    """Write a JSON metrics blob to ``ai:metrics:{call_id}`` (overwrite).

    The blob is whatever the orchestrator wants to expose — typically a
    dict containing state, OrchestratorStats fields, the interruption
    metrics, and the component health table.
    """

    payload = {**payload, "ts": time.time()}
    try:
        await memory._r.set(  # noqa: SLF001
            _metrics_key(call_id),
            json.dumps(payload),
            ex=memory.ttl_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "ai.interruption.metrics_publish_failed",
            call_id=call_id,
            error=str(exc),
        )


async def read_metrics_snapshot(
    memory: ConversationMemory, *, call_id: str
) -> dict[str, Any] | None:
    try:
        blob = await memory._r.get(_metrics_key(call_id))  # noqa: SLF001
    except Exception as exc:
        raise AIMemoryError(f"redis metrics fetch failed: {exc}") from exc
    if not blob:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None
