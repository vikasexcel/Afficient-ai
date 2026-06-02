"""Latency + performance benchmarking primitives.

Two cooperating pieces:

* :class:`BenchmarkRecorder` — process-wide singleton that buffers
  ``(category, name, latency_ms, success, metadata)`` samples emitted by
  the latency/performance suites.
* :class:`BenchmarkStats` — statistical roll-up (avg/min/max/p50/p95/p99,
  success rate, failure rate) materialised on demand.

Tests use the :func:`measure` context manager or :func:`measure_async`
async context manager to time a single iteration and push a sample into
the recorder. The :mod:`tests._support.reporter` writes a JSON +
HTML summary at session end.

Design constraints:
* No third-party deps; statistics use the stdlib only so this works on
  any Python 3.10+ environment.
* Recorder is thread-safe; latency benchmarks may parallelise.
* Empty categories don't crash the report — they just render as
  "no samples".
"""

from __future__ import annotations

import math
import os
import statistics
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Samples + recorder
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    """One measured iteration."""

    category: str
    name: str
    latency_ms: float
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class BenchmarkStats:
    """Statistical roll-up for one (category, name) pair."""

    category: str
    name: str
    count: int
    successes: int
    failures: int
    avg_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    stddev_ms: float
    success_rate: float
    failure_rate: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "name": self.name,
            "count": self.count,
            "successes": self.successes,
            "failures": self.failures,
            "avg_ms": round(self.avg_ms, 3),
            "min_ms": round(self.min_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "stddev_ms": round(self.stddev_ms, 3),
            "success_rate": round(self.success_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "metadata": self.metadata,
        }


def _percentile(values: list[float], pct: float) -> float:
    """Inclusive linear-interpolation percentile (matches numpy default)."""

    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (pct / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


class BenchmarkRecorder:
    """Thread-safe in-memory sample buffer with a single global instance.

    The :func:`get_recorder` helper returns the process-wide instance so
    tests can simply ``from tests._support.benchmark import get_recorder``
    without juggling fixtures.
    """

    def __init__(self) -> None:
        self._samples: list[Sample] = []
        self._lock = threading.Lock()
        self._started_at = time.time()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        category: str,
        name: str,
        latency_ms: float,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Sample:
        """Append one sample. Returns the stored :class:`Sample`."""

        sample = Sample(
            category=category,
            name=name,
            latency_ms=float(latency_ms),
            success=bool(success),
            metadata=dict(metadata or {}),
            error=error,
        )
        with self._lock:
            self._samples.append(sample)
        return sample

    def extend(self, samples: Iterable[Sample]) -> None:
        with self._lock:
            self._samples.extend(samples)

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._started_at = time.time()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @property
    def samples(self) -> list[Sample]:
        with self._lock:
            return list(self._samples)

    @property
    def started_at(self) -> float:
        return self._started_at

    def stats(self) -> list[BenchmarkStats]:
        """Roll samples up into one :class:`BenchmarkStats` per (cat,name)."""

        grouped: dict[tuple[str, str], list[Sample]] = {}
        with self._lock:
            for s in self._samples:
                grouped.setdefault((s.category, s.name), []).append(s)

        out: list[BenchmarkStats] = []
        for (cat, name), group in grouped.items():
            latencies = [g.latency_ms for g in group]
            successes = sum(1 for g in group if g.success)
            failures = len(group) - successes
            # Merge metadata across iterations: last-write-wins for scalars,
            # but stable per-sample fields (e.g. provider) survive.
            merged_meta: dict[str, Any] = {}
            for g in group:
                merged_meta.update(g.metadata)
            stddev = statistics.pstdev(latencies) if len(latencies) > 1 else 0.0
            out.append(
                BenchmarkStats(
                    category=cat,
                    name=name,
                    count=len(group),
                    successes=successes,
                    failures=failures,
                    avg_ms=statistics.fmean(latencies),
                    min_ms=min(latencies),
                    max_ms=max(latencies),
                    p50_ms=_percentile(latencies, 50),
                    p95_ms=_percentile(latencies, 95),
                    p99_ms=_percentile(latencies, 99),
                    stddev_ms=stddev,
                    success_rate=successes / len(group) if group else 0.0,
                    failure_rate=failures / len(group) if group else 0.0,
                    metadata=merged_meta,
                )
            )
        out.sort(key=lambda s: (s.category, s.name))
        return out


_RECORDER: BenchmarkRecorder | None = None
_RECORDER_LOCK = threading.Lock()


def get_recorder() -> BenchmarkRecorder:
    """Lazily allocate the process-wide :class:`BenchmarkRecorder`."""

    global _RECORDER
    if _RECORDER is None:
        with _RECORDER_LOCK:
            if _RECORDER is None:
                _RECORDER = BenchmarkRecorder()
    return _RECORDER


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


@contextmanager
def measure(
    category: str,
    name: str,
    *,
    metadata: dict[str, Any] | None = None,
    recorder: BenchmarkRecorder | None = None,
):
    """Sync context manager that times its body and records a sample.

    On exception the sample is recorded as ``success=False`` and the
    exception is re-raised. Latency is measured via :func:`time.perf_counter`.
    """

    rec = recorder or get_recorder()
    started = time.perf_counter()
    success = True
    err: str | None = None
    try:
        yield
    except Exception as exc:  # noqa: BLE001 — we re-raise below
        success = False
        err = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        latency_ms = (time.perf_counter() - started) * 1000.0
        rec.record(
            category=category,
            name=name,
            latency_ms=latency_ms,
            success=success,
            metadata=metadata,
            error=err,
        )


@asynccontextmanager
async def measure_async(
    category: str,
    name: str,
    *,
    metadata: dict[str, Any] | None = None,
    recorder: BenchmarkRecorder | None = None,
):
    """Async equivalent of :func:`measure`."""

    rec = recorder or get_recorder()
    started = time.perf_counter()
    success = True
    err: str | None = None
    try:
        yield
    except Exception as exc:  # noqa: BLE001 — we re-raise below
        success = False
        err = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        latency_ms = (time.perf_counter() - started) * 1000.0
        rec.record(
            category=category,
            name=name,
            latency_ms=latency_ms,
            success=success,
            metadata=metadata,
            error=err,
        )


def run_iterations(
    fn,
    *,
    category: str,
    name: str,
    iterations: int,
    metadata: dict[str, Any] | None = None,
    warmup: int = 0,
) -> list[Sample]:
    """Run ``fn()`` ``iterations`` times and record each call.

    ``warmup`` calls run first and are NOT recorded. Useful for JIT-style
    warm caches (Postgres prepared statements, etc.).
    """

    rec = get_recorder()
    out: list[Sample] = []
    for _ in range(max(0, warmup)):
        try:
            fn()
        except Exception:
            pass
    for _ in range(iterations):
        started = time.perf_counter()
        success = True
        err: str | None = None
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            success = False
            err = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000.0
        out.append(
            rec.record(
                category=category,
                name=name,
                latency_ms=latency_ms,
                success=success,
                metadata=metadata,
                error=err,
            )
        )
    return out


async def run_iterations_async(
    fn,
    *,
    category: str,
    name: str,
    iterations: int,
    metadata: dict[str, Any] | None = None,
    warmup: int = 0,
) -> list[Sample]:
    """Async equivalent of :func:`run_iterations`.

    ``fn`` should be an async callable (e.g. ``async def``). The function
    is awaited; coroutines may also be passed via lambdas.
    """

    rec = get_recorder()
    out: list[Sample] = []
    for _ in range(max(0, warmup)):
        try:
            await fn()
        except Exception:
            pass
    for _ in range(iterations):
        started = time.perf_counter()
        success = True
        err: str | None = None
        try:
            await fn()
        except Exception as exc:  # noqa: BLE001
            success = False
            err = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000.0
        out.append(
            rec.record(
                category=category,
                name=name,
                latency_ms=latency_ms,
                success=success,
                metadata=metadata,
                error=err,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Environment helpers (used by tests to gate external integrations)
# ---------------------------------------------------------------------------


def _flag(env_name: str, default: bool = False) -> bool:
    val = os.environ.get(env_name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def external_enabled() -> bool:
    """Master switch: real network calls to OpenAI/Deepgram/etc.

    Off by default so the suite stays hermetic. Enable via
    ``RUN_EXTERNAL_BENCH=1`` when you want to record real-provider numbers.
    """

    return _flag("RUN_EXTERNAL_BENCH", default=False)


def livekit_enabled() -> bool:
    return _flag("RUN_LIVEKIT_BENCH", default=external_enabled())


def openai_enabled() -> bool:
    return _flag("RUN_OPENAI_BENCH", default=external_enabled())


def deepgram_enabled() -> bool:
    return _flag("RUN_DEEPGRAM_BENCH", default=external_enabled())


def elevenlabs_enabled() -> bool:
    return _flag("RUN_ELEVENLABS_BENCH", default=external_enabled())


def twilio_enabled() -> bool:
    return _flag("RUN_TWILIO_BENCH", default=external_enabled())
