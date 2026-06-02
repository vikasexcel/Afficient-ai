"""Unit tests for the rule-based BANT / MEDDICC qualifier."""

from __future__ import annotations

import pytest

from modules.ai.qualification import (
    QualificationFramework,
    QualificationState,
    QualificationTracker,
)


pytestmark = pytest.mark.unit


def test_bant_empty_state_is_not_started():
    state = QualificationTracker.empty(QualificationFramework.BANT)
    snap = state.snapshot()
    assert snap.framework == "BANT"
    assert snap.status == "not_started"
    assert snap.score == 0
    assert set(snap.pending_fields) == {"budget", "authority", "need", "timeline"}


def test_bant_ingests_budget_cue():
    state = QualificationTracker.empty(QualificationFramework.BANT)
    newly = state.ingest_user_turn("Our budget is around $50,000 a year")
    assert "budget" in newly
    snap = state.snapshot()
    assert "budget" in snap.answered_fields
    assert snap.status == "in_progress"


def test_bant_full_qualification_promotes_to_qualified():
    state = QualificationTracker.empty(QualificationFramework.BANT)
    state.ingest_user_turn("Our budget is $50,000")
    state.ingest_user_turn("As CTO I approve this")
    state.ingest_user_turn("We have a serious bottleneck")
    state.ingest_user_turn("We need this by next quarter")
    snap = state.snapshot()
    assert snap.score == 100
    assert snap.status == "qualified"


def test_disqualifier_short_circuits_state():
    state = QualificationTracker.empty(QualificationFramework.BANT)
    newly = state.ingest_user_turn("Please remove me from your list")
    assert newly == ["__disqualified__"]
    assert state.snapshot().status == "disqualified"


def test_empty_input_does_not_set_any_field():
    state = QualificationTracker.empty(QualificationFramework.BANT)
    assert state.ingest_user_turn("") == []
    assert state.ingest_user_turn("   ") == []
    assert state.snapshot().status == "not_started"


def test_round_trip_via_json_preserves_state():
    state = QualificationTracker.empty(QualificationFramework.BANT)
    state.ingest_user_turn("budget is $1000")
    state.ingest_user_turn("I am the decision maker")
    blob = state.to_json()
    restored = QualificationState.from_json(blob)
    assert restored.snapshot().answered_fields == state.snapshot().answered_fields
    assert restored.snapshot().score == state.snapshot().score


def test_meddicc_tracks_independently_from_bant():
    state = QualificationTracker.empty(QualificationFramework.MEDDICC)
    newly = state.ingest_user_turn("we want to reduce churn by 30%")
    assert "metrics" in newly
    snap = state.snapshot()
    assert snap.framework == "MEDDICC"
    assert "metrics" in snap.answered_fields
