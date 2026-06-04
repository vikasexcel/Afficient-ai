"""Pure-Python unit tests for the campaign scheduling helpers.

No DB / Redis / network — exercises the timezone math, business-hours
validation, next-window computation and pacing arithmetic that the
call-scheduling engine relies on.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from modules.campaign.scheduling import (
    _WEEKDAY_IDS,
    compute_scheduled_at,
    is_within_business_hours,
    next_business_window,
    pacing_allowance,
)


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Timezone conversion
# --------------------------------------------------------------------------- #


def test_compute_scheduled_at_converts_local_to_utc():
    # 09:00 IST (UTC+5:30) on 2099-01-01 == 03:30 UTC the same day.
    out = compute_scheduled_at(
        start_immediately=False,
        date="2099-01-01",
        time_str="09:00",
        tz_name="Asia/Kolkata",
    )
    assert out == datetime(2099, 1, 1, 3, 30)
    assert out.tzinfo is None  # stored naive UTC


def test_compute_scheduled_at_utc_identity():
    out = compute_scheduled_at(
        start_immediately=False,
        date="2030-06-15",
        time_str="14:00",
        tz_name="UTC",
    )
    assert out == datetime(2030, 6, 15, 14, 0)


def test_compute_scheduled_at_immediate_is_none():
    assert (
        compute_scheduled_at(
            start_immediately=True, date=None, time_str=None, tz_name="UTC"
        )
        is None
    )


def test_compute_scheduled_at_bad_input_is_none():
    assert (
        compute_scheduled_at(
            start_immediately=False,
            date="not-a-date",
            time_str="09:00",
            tz_name="UTC",
        )
        is None
    )


# --------------------------------------------------------------------------- #
# Business-hours validation
# --------------------------------------------------------------------------- #


def test_business_hours_none_always_allowed():
    assert is_within_business_hours(None, "UTC", datetime(2030, 1, 1, 3, 0))


def test_business_hours_inside_window():
    bh = {"days": [], "start": "09:00", "end": "17:00"}
    # 12:00 UTC is inside 09:00-17:00.
    assert is_within_business_hours(bh, "UTC", datetime(2030, 1, 1, 12, 0))


def test_business_hours_outside_time_window():
    bh = {"days": [], "start": "09:00", "end": "17:00"}
    assert not is_within_business_hours(bh, "UTC", datetime(2030, 1, 1, 20, 0))


def test_business_hours_wrong_weekday():
    # 2030-01-01 is a Tuesday; restrict to Mondays only.
    bh = {"days": ["mon"], "start": "00:00", "end": "23:59"}
    assert not is_within_business_hours(bh, "UTC", datetime(2030, 1, 1, 12, 0))


def test_business_hours_respects_timezone():
    # 04:00 UTC == 09:30 IST -> inside a 09:00-17:00 IST window.
    bh = {"days": [], "start": "09:00", "end": "17:00"}
    assert is_within_business_hours(
        bh, "Asia/Kolkata", datetime(2030, 1, 1, 4, 0)
    )
    # 02:00 UTC == 07:30 IST -> before the window opens.
    assert not is_within_business_hours(
        bh, "Asia/Kolkata", datetime(2030, 1, 1, 2, 0)
    )


# --------------------------------------------------------------------------- #
# Next business window
# --------------------------------------------------------------------------- #


def test_next_window_returns_now_when_inside():
    bh = {"days": [], "start": "09:00", "end": "17:00"}
    now = datetime(2030, 1, 1, 12, 0)
    assert next_business_window(bh, "UTC", now) == now


def test_next_window_same_day_before_open():
    bh = {"days": [], "start": "09:00", "end": "17:00"}
    now = datetime(2030, 1, 1, 6, 0)  # before 09:00
    assert next_business_window(bh, "UTC", now) == datetime(2030, 1, 1, 9, 0)


def test_next_window_rolls_to_next_day_after_close():
    bh = {"days": [], "start": "09:00", "end": "17:00"}
    now = datetime(2030, 1, 1, 20, 0)  # after 17:00
    assert next_business_window(bh, "UTC", now) == datetime(2030, 1, 2, 9, 0)


def test_next_window_skips_to_allowed_weekday():
    bh = {"days": ["mon"], "start": "09:00", "end": "17:00"}
    now = datetime(2030, 1, 1, 20, 0)  # Tuesday evening
    nxt = next_business_window(bh, "UTC", now)
    assert _WEEKDAY_IDS[nxt.weekday()] == "mon"
    assert (nxt.hour, nxt.minute) == (9, 0)


# --------------------------------------------------------------------------- #
# Pacing arithmetic
# --------------------------------------------------------------------------- #


def test_pacing_unlimited_when_both_zero():
    assert (
        pacing_allowance(
            calls_per_hour=0,
            max_concurrent_calls=0,
            running_now=100,
            dispatched_last_hour=100,
        )
        == 1_000_000
    )


def test_pacing_per_tick_rate_cap():
    # 120/hour over a 60s tick -> 2 per tick.
    assert (
        pacing_allowance(
            calls_per_hour=120,
            max_concurrent_calls=0,
            running_now=0,
            dispatched_last_hour=0,
            tick_seconds=60,
        )
        == 2
    )


def test_pacing_rolling_hour_cap():
    # Big per-tick window but only 1 call left in the rolling hour.
    assert (
        pacing_allowance(
            calls_per_hour=10,
            max_concurrent_calls=0,
            running_now=0,
            dispatched_last_hour=9,
            tick_seconds=3600,
        )
        == 1
    )


def test_pacing_concurrency_cap():
    assert (
        pacing_allowance(
            calls_per_hour=0,
            max_concurrent_calls=5,
            running_now=4,
            dispatched_last_hour=0,
        )
        == 1
    )


def test_pacing_never_negative():
    assert (
        pacing_allowance(
            calls_per_hour=0,
            max_concurrent_calls=2,
            running_now=5,
            dispatched_last_hour=0,
        )
        == 0
    )
