"""Pure scheduling helpers for campaigns.

Dependency-free (stdlib ``zoneinfo``) so the timezone / business-hours math
can be unit-tested without FastAPI or the DB.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")

# Map the frontend weekday ids to Python's Monday=0..Sunday=6.
_WEEKDAY_IDS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _safe_zone(tz_name: str | None) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def compute_scheduled_at(
    *,
    start_immediately: bool,
    date: str | None,
    time_str: str | None,
    tz_name: str | None,
) -> datetime | None:
    """Convert a local date/time + IANA timezone to a UTC ``datetime``.

    Returns ``None`` when the campaign should start immediately or when the
    date/time are missing/malformed (caller treats ``None`` as "now").
    """

    if start_immediately:
        return None
    if not date or not time_str:
        return None
    if not _DATE_RE.match(date) or not _TIME_RE.match(time_str):
        return None

    try:
        y, m, d = (int(p) for p in date.split("-"))
        hh, mm = (int(p) for p in time_str.split(":"))
    except ValueError:
        return None

    zone = _safe_zone(tz_name)
    local_dt = datetime(y, m, d, hh, mm, tzinfo=zone)
    # Store naive UTC to match the rest of the codebase (DateTime columns are
    # naive and populated from ``datetime.utcnow``).
    return local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def is_within_business_hours(
    business_hours: dict | None,
    tz_name: str | None,
    now_utc: datetime,
) -> bool:
    """True when ``now_utc`` falls inside the configured calling window.

    No config == always allowed. The window is interpreted in ``tz_name``
    (falling back to UTC).
    """

    if not business_hours:
        return True

    days = business_hours.get("days") or []
    start = business_hours.get("start") or "00:00"
    end = business_hours.get("end") or "23:59"

    zone = _safe_zone(tz_name)
    # ``now_utc`` is naive UTC; attach UTC then convert to the target zone.
    local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)

    if days:
        weekday_id = _WEEKDAY_IDS[local.weekday()]
        if weekday_id not in days:
            return False

    try:
        sh, sm = (int(p) for p in start.split(":"))
        eh, em = (int(p) for p in end.split(":"))
    except ValueError:
        return True

    start_t = time(sh, sm)
    end_t = time(eh, em)
    now_t = local.time()
    return start_t <= now_t <= end_t


def next_business_window(
    business_hours: dict | None,
    tz_name: str | None,
    now_utc: datetime,
) -> datetime:
    """Return the next UTC instant calls are allowed to start.

    When ``now_utc`` is already inside the window it is returned unchanged.
    Otherwise we scan forward day-by-day (up to 8 days, covering any weekly
    day-of-week gap) for the next allowed day and return that day's ``start``
    time converted back to naive UTC. Returns ``now_utc`` when there is no
    business-hours config (always allowed).
    """

    if not business_hours:
        return now_utc

    if is_within_business_hours(business_hours, tz_name, now_utc):
        return now_utc

    days = business_hours.get("days") or []
    start = business_hours.get("start") or "00:00"
    try:
        sh, sm = (int(p) for p in start.split(":"))
    except ValueError:
        sh, sm = 0, 0

    zone = _safe_zone(tz_name)
    local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)

    # Today still ahead of the start time? Use today's opening.
    candidate = local.replace(hour=sh, minute=sm, second=0, microsecond=0)
    if candidate <= local:
        candidate = candidate + timedelta(days=1)

    for _ in range(8):
        allowed_day = (
            not days or _WEEKDAY_IDS[candidate.weekday()] in days
        )
        if allowed_day:
            return candidate.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        candidate = candidate + timedelta(days=1)

    # Defensive fallback: shouldn't happen with a sane weekly config.
    return candidate.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def pacing_allowance(
    *,
    calls_per_hour: int,
    max_concurrent_calls: int,
    running_now: int,
    dispatched_last_hour: int,
    tick_seconds: float = 60.0,
) -> int:
    """How many *new* calls may be dispatched on this scheduler tick.

    Three limits are intersected (each ``0`` == unlimited):

    * per-tick rate    — ``calls_per_hour`` spread across the tick interval
    * rolling-hour cap — ``calls_per_hour`` minus what already went out
    * concurrency      — ``max_concurrent_calls`` minus what's in flight

    The result is never negative.
    """

    limits: list[int] = []

    if calls_per_hour and calls_per_hour > 0:
        per_tick = math.ceil(calls_per_hour * tick_seconds / 3600.0)
        per_tick = max(1, per_tick)
        limits.append(per_tick)
        limits.append(calls_per_hour - dispatched_last_hour)

    if max_concurrent_calls and max_concurrent_calls > 0:
        limits.append(max_concurrent_calls - running_now)

    if not limits:
        # Both constraints unlimited.
        return 1_000_000

    return max(0, min(limits))
