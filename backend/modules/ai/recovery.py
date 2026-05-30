"""Async retry + timeout primitives for the voice pipeline.

The OpenAI / Deepgram / ElevenLabs / LiveKit SDKs all expose narrow
retry knobs (or none at all). On top of those, the orchestrator needs:

* **Bounded retry with exponential backoff** for transient provider
  failures (rate limit, 5xx, dropped sockets) that should not be
  surfaced to the caller mid-conversation.
* **Hard deadlines** per call attempt — a turn that exceeds N seconds
  must be dropped and a fallback line spoken so the lead doesn't sit
  through dead air while we wait for the LLM.

This module is dependency-free (stdlib + ``common.logging``) so it can
be imported from any layer without creating cycles.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, TypeVar

from common.logging import get_logger

log = get_logger("ai.recovery")

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """Declarative retry config consumed by :func:`with_retry`."""

    max_attempts: int = 3
    base_backoff_seconds: float = 0.4
    max_backoff_seconds: float = 4.0
    jitter: float = 0.15  # ±15% randomisation to avoid synchronised retries
    # Exceptions that should trigger a retry. Anything else propagates.
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    # If set, the callable is invoked with (attempt, exc) before sleeping
    # so callers can record metrics / log structured events.
    on_retry: Callable[[int, BaseException], None] | None = field(
        default=None, repr=False
    )

    def compute_backoff(self, attempt: int) -> float:
        # attempt is 1-indexed (failure #1 → sleep before attempt #2)
        delay = min(
            self.max_backoff_seconds,
            self.base_backoff_seconds * (2 ** (attempt - 1)),
        )
        if self.jitter:
            spread = delay * self.jitter
            delay = delay + random.uniform(-spread, spread)
        return max(0.0, delay)


async def with_retry(
    coro_factory: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    label: str = "op",
) -> T:
    """Run ``coro_factory()`` with bounded retries on the configured errors.

    ``coro_factory`` is a *zero-arg callable* (not an awaitable) so we can
    re-invoke the underlying call each attempt — awaiting the same coroutine
    twice would raise ``RuntimeError: cannot reuse already awaited coroutine``.
    """

    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await coro_factory()
        except policy.retry_on as exc:
            last_exc = exc
            if attempt >= policy.max_attempts:
                log.warning(
                    "ai.recovery.exhausted",
                    label=label,
                    attempts=attempt,
                    error=type(exc).__name__,
                )
                raise
            delay = policy.compute_backoff(attempt)
            if policy.on_retry is not None:
                try:
                    policy.on_retry(attempt, exc)
                except Exception:  # noqa: BLE001 — on_retry must not break us
                    pass
            log.info(
                "ai.recovery.retrying",
                label=label,
                attempt=attempt,
                next_in_ms=int(delay * 1000),
                error=type(exc).__name__,
            )
            await asyncio.sleep(delay)
    # Unreachable in practice; the for-loop either returns or re-raises.
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{label}: with_retry exited without result or error")


async def with_timeout(
    coro: Awaitable[T],
    *,
    timeout_seconds: float,
    label: str = "op",
) -> T:
    """``asyncio.wait_for`` wrapper that logs the timeout uniformly."""

    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        log.warning(
            "ai.recovery.timeout",
            label=label,
            timeout_ms=int(timeout_seconds * 1000),
        )
        raise


# ---------------------------------------------------------------------------
# Component health tracker — useful for monitoring recovery success rate
# ---------------------------------------------------------------------------


@dataclass
class ComponentHealth:
    """Counters for one upstream component (LLM, STT, TTS, transport)."""

    name: str
    failures: int = 0
    retries: int = 0
    recoveries: int = 0  # failures that were ultimately recovered
    fatal: int = 0  # failures not recoverable in-call
    last_error: str | None = None
    last_error_ts: float | None = None

    def record_retry(self, exc: BaseException) -> None:
        self.retries += 1
        self.last_error = type(exc).__name__
        self.last_error_ts = time.monotonic()

    def record_failure(self, exc: BaseException) -> None:
        self.failures += 1
        self.last_error = f"{type(exc).__name__}: {exc}"
        self.last_error_ts = time.monotonic()

    def record_recovery(self) -> None:
        self.recoveries += 1

    def record_fatal(self, exc: BaseException) -> None:
        self.fatal += 1
        self.last_error = f"{type(exc).__name__}: {exc}"
        self.last_error_ts = time.monotonic()

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "failures": self.failures,
            "retries": self.retries,
            "recoveries": self.recoveries,
            "fatal": self.fatal,
            "last_error": self.last_error,
        }


class HealthRegistry:
    """Container for per-component :class:`ComponentHealth` records."""

    def __init__(self, components: Iterable[str] = ()) -> None:
        self._by_name: dict[str, ComponentHealth] = {
            name: ComponentHealth(name=name) for name in components
        }

    def get(self, name: str) -> ComponentHealth:
        if name not in self._by_name:
            self._by_name[name] = ComponentHealth(name=name)
        return self._by_name[name]

    def all(self) -> list[ComponentHealth]:
        return list(self._by_name.values())

    def as_dict(self) -> dict:
        return {name: c.as_dict() for name, c in self._by_name.items()}

    @property
    def recovery_success_rate(self) -> float:
        """Recoveries / failures across all components."""

        total_failures = sum(c.failures for c in self._by_name.values())
        total_recoveries = sum(c.recoveries for c in self._by_name.values())
        if total_failures == 0:
            return 1.0
        return total_recoveries / total_failures
