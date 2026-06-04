"""Pure-Python unit tests for the Retry Execution Engine.

No DB / Redis / network — exercises the retryable-outcome vocabulary, the
fixed/exponential backoff math, ``calculate_next_retry`` and the in-place
``process_outcome`` decision table (driven against a lightweight stand-in for
the ORM ``Execution`` row).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from modules.campaign.retry import (
    BACKOFF_EXPONENTIAL,
    BACKOFF_FIXED,
    NON_RETRYABLE_OUTCOMES,
    RETRYABLE_OUTCOMES,
    backoff_delay_minutes,
    calculate_next_retry,
    is_retryable,
    process_outcome,
    resolve_retry_config,
)


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Retryable outcome vocabulary
# --------------------------------------------------------------------------- #


def test_is_retryable_true_for_transient_outcomes():
    for outcome in ("no_answer", "busy", "voicemail", "failed", "temporary_error"):
        assert is_retryable(outcome), outcome
    assert RETRYABLE_OUTCOMES == {
        "no_answer",
        "busy",
        "voicemail",
        "failed",
        "temporary_error",
    }


def test_is_retryable_false_for_terminal_outcomes():
    for outcome in (
        "qualified",
        "meeting_booked",
        "completed",
        "opted_out",
        "do_not_call",
    ):
        assert not is_retryable(outcome), outcome
    assert "qualified" in NON_RETRYABLE_OUTCOMES


def test_is_retryable_normalizes_hyphen_case_and_space():
    # Telephony emits "no-answer"; config uses "no_answer".
    assert is_retryable("No-Answer")
    assert is_retryable("  BUSY ")
    assert not is_retryable("QUALIFIED")
    assert not is_retryable(None)


# --------------------------------------------------------------------------- #
# Backoff math
# --------------------------------------------------------------------------- #


def test_fixed_backoff_is_constant():
    for attempt in (1, 2, 3, 4, 5):
        assert (
            backoff_delay_minutes(
                attempt,
                retry_interval_minutes=15,
                backoff_strategy=BACKOFF_FIXED,
            )
            == 15
        )


def test_exponential_backoff_doubles():
    expected = {1: 15, 2: 30, 3: 60, 4: 120, 5: 240}
    for attempt, minutes in expected.items():
        assert (
            backoff_delay_minutes(
                attempt,
                retry_interval_minutes=15,
                backoff_strategy=BACKOFF_EXPONENTIAL,
            )
            == minutes
        )


def test_calculate_next_retry_fixed():
    now = datetime(2030, 1, 1, 12, 0)
    cfg = {
        "max_attempts": 5,
        "retry_interval_minutes": 15,
        "backoff_strategy": "fixed",
    }
    assert calculate_next_retry(1, cfg, now=now) == datetime(2030, 1, 1, 12, 15)
    assert calculate_next_retry(3, cfg, now=now) == datetime(2030, 1, 1, 12, 15)


def test_calculate_next_retry_exponential():
    now = datetime(2030, 1, 1, 12, 0)
    cfg = {"retry_interval_minutes": 15, "backoff_strategy": "exponential"}
    assert calculate_next_retry(1, cfg, now=now) == datetime(2030, 1, 1, 12, 15)
    assert calculate_next_retry(2, cfg, now=now) == datetime(2030, 1, 1, 12, 30)
    assert calculate_next_retry(3, cfg, now=now) == datetime(2030, 1, 1, 13, 0)
    assert calculate_next_retry(4, cfg, now=now) == datetime(2030, 1, 1, 14, 0)


# --------------------------------------------------------------------------- #
# Config resolution (new + legacy shapes)
# --------------------------------------------------------------------------- #


def test_resolve_config_defaults():
    cfg = resolve_retry_config(None)
    assert cfg["max_attempts"] == 5
    assert cfg["retry_interval_minutes"] == 15
    assert cfg["backoff_strategy"] == "fixed"
    assert cfg["retry_on"] is None


def test_resolve_config_legacy_backoff_minutes():
    cfg = resolve_retry_config({"max_attempts": 3, "backoff_minutes": 20})
    assert cfg["max_attempts"] == 3
    assert cfg["retry_interval_minutes"] == 20
    assert cfg["backoff_strategy"] == "fixed"


def test_resolve_config_prefers_new_interval_over_legacy():
    cfg = resolve_retry_config(
        {"retry_interval_minutes": 5, "backoff_minutes": 99}
    )
    assert cfg["retry_interval_minutes"] == 5


def test_resolve_config_bad_strategy_falls_back():
    cfg = resolve_retry_config({"backoff_strategy": "nonsense"})
    assert cfg["backoff_strategy"] == "fixed"


# --------------------------------------------------------------------------- #
# In-place outcome processing
# --------------------------------------------------------------------------- #


class _FakeExecution:
    """Minimal stand-in for the ORM ``Execution`` row (no DB)."""

    def __init__(self, attempt_number: int = 1, context: dict | None = None):
        self.attempt_number = attempt_number
        self.context = context
        self.status = "running"
        self.outcome = None
        self.retry_status = "pending"
        self.next_retry_at = None
        self.last_failure_reason = None


_FIXED_CFG = {
    "max_attempts": 3,
    "retry_interval_minutes": 15,
    "backoff_strategy": "fixed",
}


def test_process_outcome_schedules_retry_when_attempts_remain():
    ex = _FakeExecution(attempt_number=1)
    process_outcome(
        None,
        ex,
        "no_answer",
        retry_config=_FIXED_CFG,
        now=datetime(2030, 1, 1, 12, 0),
        commit=False,
    )
    assert ex.status == "failed"
    assert ex.retry_status == "scheduled"
    assert ex.attempt_number == 2
    assert ex.next_retry_at == datetime(2030, 1, 1, 12, 15)
    assert ex.outcome == "no_answer"
    # History trail appended for the attempt that just ran.
    assert ex.context["retry_history"][-1]["attempt_number"] == 1


def test_process_outcome_exhausts_at_max_attempts():
    ex = _FakeExecution(attempt_number=3)
    process_outcome(None, ex, "busy", retry_config=_FIXED_CFG, commit=False)
    assert ex.status == "failed"
    assert ex.retry_status == "exhausted"
    assert ex.attempt_number == 3  # not incremented past the cap
    assert ex.next_retry_at is None


def test_process_outcome_terminal_success_completes():
    ex = _FakeExecution(attempt_number=2)
    process_outcome(
        None, ex, "qualified", retry_config=_FIXED_CFG, commit=False
    )
    assert ex.status == "completed"
    assert ex.retry_status == "completed"
    assert ex.next_retry_at is None


def test_process_outcome_no_config_is_terminal_failure():
    ex = _FakeExecution(attempt_number=1)
    process_outcome(None, ex, "failed", retry_config=None, commit=False)
    assert ex.status == "failed"
    assert ex.retry_status is None
    assert ex.next_retry_at is None


def test_process_outcome_retry_on_allowlist_restricts():
    # voicemail is globally retryable but excluded by this campaign's allow-list.
    cfg = {**_FIXED_CFG, "retry_on": ["no_answer", "busy"]}
    ex = _FakeExecution(attempt_number=1)
    process_outcome(None, ex, "voicemail", retry_config=cfg, commit=False)
    assert ex.status == "completed"
    assert ex.retry_status == "completed"
