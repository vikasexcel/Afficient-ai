"""Unit tests for the barge-in interruption event types."""

from __future__ import annotations

import json
import time

import pytest

from modules.ai.interruption import InterruptionEvent, InterruptionMetrics


pytestmark = pytest.mark.unit


def _event(**overrides) -> InterruptionEvent:
    base = dict(
        call_id="call-1",
        ts_unix=time.time(),
        stt_event_ts_ms=120,
        trigger_latency_ms=15,
        silence_latency_ms=42,
        source="speech_started",
        state_before="SPEAKING",
        partial_text=None,
    )
    base.update(overrides)
    return InterruptionEvent(**base)


def test_event_round_trip_via_json():
    ev = _event()
    restored = InterruptionEvent.from_json(ev.to_json())
    assert restored == ev


def test_event_to_dict_is_serialisable():
    ev = _event()
    blob = json.dumps(ev.to_dict())
    assert "speech_started" in blob


def test_metrics_record_updates_running_totals():
    m = InterruptionMetrics()
    m.record(_event(trigger_latency_ms=10, silence_latency_ms=40))
    m.record(_event(trigger_latency_ms=30, silence_latency_ms=60, source="partial"))
    assert m.total == 2
    assert m.by_source == {"speech_started": 1, "partial": 1}
    assert m.avg_trigger_latency_ms == 20.0
    assert m.avg_silence_latency_ms == 50.0
    snap = m.as_dict()
    assert snap["total"] == 2
    assert snap["avg_silence_latency_ms"] == 50.0


def test_empty_metrics_handle_division_by_zero_safely():
    m = InterruptionMetrics()
    assert m.avg_trigger_latency_ms == 0.0
    assert m.avg_silence_latency_ms == 0.0
