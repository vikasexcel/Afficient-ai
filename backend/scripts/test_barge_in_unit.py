#!/usr/bin/env python3
"""Unit tests for the orchestrator's barge-in + recovery machinery.

Runs in <1s without any external services. Uses minimal stubs for STT,
TTS, AI, and Redis so we can drive the state machine through every
interesting path.

Usage:
    cd backend
    source venv/bin/activate
    python scripts/test_barge_in_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from collections import deque
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import patch

REPO_BACKEND = Path(__file__).resolve().parent.parent
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.ai.exceptions import AIProviderError, AIRateLimitError, AITimeoutError  # noqa: E402
from modules.ai.recovery import RetryPolicy, with_retry, with_timeout  # noqa: E402
from modules.ai.state import (  # noqa: E402
    ConversationState,
    SessionStateMachine,
)
from modules.stt.schema import TranscriptEvent, TranscriptEventKind  # noqa: E402


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal in-memory redis substitute for ConversationMemory tests.

    Only implements the calls the orchestrator + InterruptionLog touch.
    """

    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.strings[key] = value

    async def delete(self, key: str) -> None:
        self.strings.pop(key, None)
        self.lists.pop(key, None)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        return items[start : end + 1 if end != -1 else None]

    async def aclose(self) -> None:
        pass

    def pipeline(self, transaction: bool = True):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, parent: _FakeRedis) -> None:
        self._parent = parent
        self._ops: list = []

    def rpush(self, key, value):
        self._ops.append(("rpush", key, value))
        return self

    def ltrim(self, key, start, end):
        self._ops.append(("ltrim", key, start, end))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    def lrange(self, key, start, end):
        self._ops.append(("lrange", key, start, end))
        return self

    def get(self, key):
        self._ops.append(("get", key))
        return self

    async def execute(self):
        results = []
        for op in self._ops:
            tag = op[0]
            if tag == "rpush":
                _, key, value = op
                self._parent.lists.setdefault(key, []).append(value)
                results.append(len(self._parent.lists[key]))
            elif tag == "ltrim":
                _, key, start, end = op
                items = self._parent.lists.get(key, [])
                if end == -1:
                    items = items[start:]
                else:
                    items = items[start : end + 1]
                self._parent.lists[key] = items
                results.append(True)
            elif tag == "expire":
                results.append(True)
            elif tag == "lrange":
                _, key, start, end = op
                items = self._parent.lists.get(key, [])
                results.append(
                    items[start : end + 1 if end != -1 else None]
                )
            elif tag == "get":
                _, key = op
                results.append(self._parent.strings.get(key))
        self._ops.clear()
        return results


class _FakeMemory:
    """Stand-in for :class:`ConversationMemory` that talks to _FakeRedis."""

    def __init__(self) -> None:
        self._r = _FakeRedis()
        self.ttl_seconds = 3600

    async def aclose(self) -> None:
        pass


class _FakeAIService:
    """Mimic the subset of AIService the orchestrator touches."""

    def __init__(self, *, fail_n_turns: int = 0) -> None:
        self.memory = _FakeMemory()
        self.start_called = 0
        self.turn_calls = 0
        self.finalize_called = 0
        self._fail_n_turns = fail_n_turns
        self._raised = 0

    async def start_call(self, **kwargs):
        self.start_called += 1

    async def respond_turn(self, **kwargs):
        self.turn_calls += 1
        if self._raised < self._fail_n_turns:
            self._raised += 1
            raise AIProviderError("simulated provider error")

        class _Stats:
            latency_ms = 120
            ttft_ms = 60
            prompt_tokens = 10
            completion_tokens = 5
            total_tokens = 15
            finish_reason = "stop"
            model = "gpt-4o"

        class _Qual:
            status = "in_progress"
            score = 25

        class _Result:
            reply = f"reply #{self.turn_calls}"
            stats = _Stats()
            qualification = _Qual()
            history_length = self.turn_calls * 2

        return _Result()

    async def finalize_call(self, **kwargs):
        self.finalize_called += 1
        return {}


class _FakeTTSSession:
    """In-memory TTS session that records interrupts."""

    def __init__(self) -> None:
        self._speaking = False
        self._speak_task: asyncio.Task | None = None
        self.spoken: list[str] = []
        self.interrupt_count = 0

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    async def speak(self, text: str, *, wait_for_playout: bool = True):
        self._speaking = True
        try:
            # "Speak" by sleeping for a bounded time; barge-in cancels this.
            await asyncio.sleep(0.5)
            self.spoken.append(text)
        finally:
            self._speaking = False

    async def interrupt(self):
        self.interrupt_count += 1
        was_speaking = self._speaking
        self._speaking = False

        class _Result:
            silence_latency_ms = 3
            dropped_buffer_ms = 150
            was_speaking_attr = was_speaking

        r = _Result()
        # rename for compatibility
        r.was_speaking = was_speaking  # type: ignore[attr-defined]
        return r


class _FakeSTTSession:
    def __init__(self, events: list[TranscriptEvent]) -> None:
        self._events = events

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        for e in self._events:
            await asyncio.sleep(0.01)
            yield e


class _FakeStreamerCtx:
    def __init__(self, target):
        self.target = target

    async def __aenter__(self):
        return self.target

    async def __aexit__(self, *exc):
        return False


class _FakeTTSStreamer:
    def __init__(self, session: _FakeTTSSession) -> None:
        self._session = session

    def open_session(self, *, room: str):
        return _FakeStreamerCtx(self._session)


class _FakeSTTStreamer:
    def __init__(self, session: _FakeSTTSession) -> None:
        self._session = session

    def open_session(self, **kwargs):
        return _FakeStreamerCtx(self._session)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class StateMachineTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_state(self):
        sm = SessionStateMachine()
        self.assertEqual(sm.state, ConversationState.LISTENING)

    async def test_transitions_recorded(self):
        sm = SessionStateMachine()
        await sm.transition(ConversationState.PROCESSING, reason="x")
        await sm.transition(ConversationState.AI_SPEAKING)
        history = list(sm.history())
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].to_state, ConversationState.PROCESSING)
        self.assertEqual(history[1].to_state, ConversationState.AI_SPEAKING)

    async def test_listener_invoked(self):
        sm = SessionStateMachine()
        seen: list[str] = []
        sm.add_listener(lambda t: seen.append(t.to_state.value))
        await sm.transition(ConversationState.PROCESSING)
        self.assertEqual(seen, ["processing"])

    async def test_async_listener_invoked(self):
        sm = SessionStateMachine()
        seen: list[str] = []

        async def listen(t):
            await asyncio.sleep(0)
            seen.append(t.to_state.value)

        sm.add_listener(listen)
        await sm.transition(ConversationState.RECOVERY)
        self.assertEqual(seen, ["recovery"])

    async def test_noop_transition(self):
        sm = SessionStateMachine()
        result = await sm.transition(ConversationState.LISTENING)
        self.assertIsNone(result)

    async def test_wait_until(self):
        sm = SessionStateMachine()

        async def flip():
            await asyncio.sleep(0.05)
            await sm.transition(ConversationState.PROCESSING)

        asyncio.create_task(flip())
        result = await sm.wait_until(ConversationState.PROCESSING, timeout=2.0)
        self.assertEqual(result, ConversationState.PROCESSING)


class RetryPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_succeeds_on_first_attempt(self):
        calls = 0

        async def op():
            nonlocal calls
            calls += 1
            return "ok"

        result = await with_retry(
            op, RetryPolicy(max_attempts=3, base_backoff_seconds=0.01)
        )
        self.assertEqual(result, "ok")
        self.assertEqual(calls, 1)

    async def test_retries_then_succeeds(self):
        calls = 0

        async def op():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise AIRateLimitError("slow down")
            return "ok"

        result = await with_retry(
            op,
            RetryPolicy(
                max_attempts=5,
                base_backoff_seconds=0.005,
                retry_on=(AIRateLimitError,),
            ),
        )
        self.assertEqual(result, "ok")
        self.assertEqual(calls, 3)

    async def test_exhausts_attempts(self):
        async def op():
            raise AITimeoutError("never works")

        with self.assertRaises(AITimeoutError):
            await with_retry(
                op,
                RetryPolicy(
                    max_attempts=2,
                    base_backoff_seconds=0.005,
                    retry_on=(AITimeoutError,),
                ),
            )

    async def test_on_retry_hook_called(self):
        events: list[int] = []

        async def op():
            raise AIRateLimitError("rate")

        with self.assertRaises(AIRateLimitError):
            await with_retry(
                op,
                RetryPolicy(
                    max_attempts=3,
                    base_backoff_seconds=0.005,
                    retry_on=(AIRateLimitError,),
                    on_retry=lambda attempt, exc: events.append(attempt),
                ),
            )
        # on_retry fires *between* attempts → twice for 3 attempts total.
        self.assertEqual(events, [1, 2])

    async def test_timeout_triggers(self):
        async def slow():
            await asyncio.sleep(0.5)

        with self.assertRaises(asyncio.TimeoutError):
            await with_timeout(slow(), timeout_seconds=0.05)


class InterruptionMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_aggregates(self):
        from modules.ai.interruption import InterruptionEvent, InterruptionMetrics

        m = InterruptionMetrics()
        m.record(
            InterruptionEvent(
                call_id="c1",
                ts_unix=time.time(),
                stt_event_ts_ms=120,
                trigger_latency_ms=3,
                silence_latency_ms=45,
                source="speech_started",
                state_before="ai_speaking",
            )
        )
        m.record(
            InterruptionEvent(
                call_id="c1",
                ts_unix=time.time(),
                stt_event_ts_ms=240,
                trigger_latency_ms=5,
                silence_latency_ms=55,
                source="partial",
                state_before="ai_speaking",
            )
        )
        self.assertEqual(m.total, 2)
        self.assertEqual(m.by_source, {"speech_started": 1, "partial": 1})
        self.assertAlmostEqual(m.avg_trigger_latency_ms, 4.0)
        self.assertAlmostEqual(m.avg_silence_latency_ms, 50.0)

    async def test_log_round_trip(self):
        from modules.ai.interruption import InterruptionEvent, InterruptionLog

        mem = _FakeMemory()
        log_store = InterruptionLog(mem)  # type: ignore[arg-type]
        await log_store.record(
            InterruptionEvent(
                call_id="c1",
                ts_unix=time.time(),
                stt_event_ts_ms=10,
                trigger_latency_ms=1,
                silence_latency_ms=2,
                source="speech_started",
                state_before="ai_speaking",
            )
        )
        events = await log_store.list_for_call("c1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source, "speech_started")


class OrchestratorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Drives the real ConversationOrchestrator with fakes."""

    async def _run_with_events(
        self,
        events: list[TranscriptEvent],
        *,
        fail_n_turns: int = 0,
    ):
        from modules.ai.orchestrator import ConversationOrchestrator

        ai = _FakeAIService(fail_n_turns=fail_n_turns)
        tts_session = _FakeTTSSession()
        tts_streamer = _FakeTTSStreamer(tts_session)
        stt_session = _FakeSTTSession(events)
        stt_streamer = _FakeSTTStreamer(stt_session)

        orch = ConversationOrchestrator(
            ai=ai,  # type: ignore[arg-type]
            stt_streamer=stt_streamer,  # type: ignore[arg-type]
            tts_streamer=tts_streamer,  # type: ignore[arg-type]
            room="r-test",
            call_id="c-test",
            opening_line=None,
            idle_timeout_seconds=2.0,
            publish_metrics=False,
        )

        async with orch.run():
            # Let the event loop drain
            await asyncio.sleep(0.5)
            orch.stop()
        return orch, ai, tts_session

    async def test_user_speaks_then_final_triggers_llm(self):
        events = [
            TranscriptEvent(
                kind=TranscriptEventKind.SPEECH_STARTED, ts_ms=100
            ),
            TranscriptEvent(
                kind=TranscriptEventKind.FINAL,
                text="hello there",
                is_final=True,
                ts_ms=600,
            ),
        ]
        orch, ai, tts = await self._run_with_events(events)
        self.assertEqual(ai.turn_calls, 1)
        self.assertEqual(orch.stats.turns, 1)
        self.assertEqual(orch.stats.barge_ins, 0)
        self.assertEqual(orch.stats.llm_errors, 0)

    async def test_barge_in_during_tts(self):
        """User speaks while TTS is mid-utterance."""
        from modules.ai.orchestrator import ConversationOrchestrator

        ai = _FakeAIService()
        tts_session = _FakeTTSSession()
        tts_streamer = _FakeTTSStreamer(tts_session)
        # First trigger a turn, then barge-in.
        events = [
            TranscriptEvent(
                kind=TranscriptEventKind.FINAL,
                text="tell me a story",
                is_final=True,
                ts_ms=100,
            ),
            # Delay so TTS is mid-speak.
            TranscriptEvent(
                kind=TranscriptEventKind.SPEECH_STARTED, ts_ms=400
            ),
        ]
        stt_session = _FakeSTTSession(events)
        stt_streamer = _FakeSTTStreamer(stt_session)

        orch = ConversationOrchestrator(
            ai=ai,  # type: ignore[arg-type]
            stt_streamer=stt_streamer,  # type: ignore[arg-type]
            tts_streamer=tts_streamer,  # type: ignore[arg-type]
            room="r-test",
            call_id="c-test",
            idle_timeout_seconds=2.0,
            publish_metrics=False,
        )

        async with orch.run():
            await asyncio.sleep(0.8)
            orch.stop()
        self.assertGreaterEqual(orch.stats.barge_ins, 1)
        self.assertGreaterEqual(tts_session.interrupt_count, 1)
        self.assertGreater(
            orch.stats.interruption_metrics.total, 0
        )

    async def test_llm_recovery(self):
        """LLM fails N times, exceeding retry budget → RECOVERY → fallback line."""
        events = [
            TranscriptEvent(
                kind=TranscriptEventKind.FINAL,
                text="hi",
                is_final=True,
                ts_ms=100,
            ),
        ]
        # Shrink the backoff so retries finish inside the test window.
        from config.settings import settings as _s

        with patch.object(_s, "AI_TURN_RETRY_BACKOFF_SECONDS", 0.01):
            # 5 forced failures > AI_TURN_MAX_ATTEMPTS, so we exhaust
            # the retry budget and fall into RECOVERY.
            from modules.ai.orchestrator import ConversationOrchestrator

            ai = _FakeAIService(fail_n_turns=5)
            tts_session = _FakeTTSSession()
            tts_streamer = _FakeTTSStreamer(tts_session)
            stt_session = _FakeSTTSession(events)
            stt_streamer = _FakeSTTStreamer(stt_session)
            orch = ConversationOrchestrator(
                ai=ai,  # type: ignore[arg-type]
                stt_streamer=stt_streamer,  # type: ignore[arg-type]
                tts_streamer=tts_streamer,  # type: ignore[arg-type]
                room="r-test",
                call_id="c-test",
                idle_timeout_seconds=3.0,
                publish_metrics=False,
            )
            async with orch.run():
                # Recovery message playback takes 0.5s in the fake TTS.
                await asyncio.sleep(1.0)
                orch.stop()
        self.assertEqual(orch.stats.llm_errors, 1)
        self.assertEqual(orch.stats.recoveries_attempted, 1)
        self.assertGreaterEqual(len(tts_session.spoken), 1)
        self.assertIn("brief issue", tts_session.spoken[-1].lower())

    async def test_partial_text_barge_in(self):
        """Long PARTIAL while TTS speaking also triggers barge-in."""
        from modules.ai.orchestrator import ConversationOrchestrator

        ai = _FakeAIService()
        tts_session = _FakeTTSSession()
        tts_streamer = _FakeTTSStreamer(tts_session)
        events = [
            TranscriptEvent(
                kind=TranscriptEventKind.FINAL,
                text="please keep talking for a while",
                is_final=True,
                ts_ms=100,
            ),
            TranscriptEvent(
                kind=TranscriptEventKind.PARTIAL,
                text="hold on",
                is_final=False,
                ts_ms=400,
            ),
        ]
        stt_session = _FakeSTTSession(events)
        stt_streamer = _FakeSTTStreamer(stt_session)

        orch = ConversationOrchestrator(
            ai=ai,  # type: ignore[arg-type]
            stt_streamer=stt_streamer,  # type: ignore[arg-type]
            tts_streamer=tts_streamer,  # type: ignore[arg-type]
            room="r-test",
            call_id="c-test",
            idle_timeout_seconds=2.0,
            publish_metrics=False,
        )

        async with orch.run():
            await asyncio.sleep(0.8)
            orch.stop()
        self.assertGreaterEqual(orch.stats.barge_ins, 1)
        self.assertGreaterEqual(
            orch.stats.interruption_metrics.by_source.get("partial", 0), 1
        )


if __name__ == "__main__":
    # Slim down logging during the test run.
    import logging

    logging.basicConfig(level=logging.WARNING)
    unittest.main(verbosity=2)
