"""Retry Execution Engine for campaign calls.

This module owns three concerns, kept deliberately separable so the math is
unit-testable without a DB:

1. **Outcome vocabulary** — which call outcomes are retryable (``is_retryable``).
2. **Backoff math** — when the next attempt should run (``calculate_next_retry``
   / ``backoff_delay_minutes``), supporting ``fixed`` and ``exponential``.
3. **Outcome processing** — :func:`process_outcome` mutates an
   :class:`~modules.campaign.execution_model.Execution` row in place: it records
   the outcome, schedules the next retry (respecting ``max_attempts``), or marks
   the row exhausted/completed.

A single execution row is retried *in place*: each failure bumps
``attempt_number`` and stamps ``next_retry_at``; the scheduler later flips the
row back to ``queued`` once that time arrives and the campaign is inside its
business-hours window.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------- #
# Outcome vocabulary
# --------------------------------------------------------------------------- #

# Transient / unsuccessful outcomes worth dialing again.
RETRYABLE_OUTCOMES = frozenset(
    {
        "no_answer",
        "busy",
        "voicemail",
        "failed",
        "temporary_error",
    }
)

# Terminal outcomes — never retry (either success or an explicit opt-out).
NON_RETRYABLE_OUTCOMES = frozenset(
    {
        "qualified",
        "meeting_booked",
        "completed",
        "opted_out",
        "do_not_call",
    }
)

# --------------------------------------------------------------------------- #
# retry_status lifecycle
# --------------------------------------------------------------------------- #

RETRY_STATUS_PENDING = "pending"
RETRY_STATUS_SCHEDULED = "scheduled"
RETRY_STATUS_EXHAUSTED = "exhausted"
RETRY_STATUS_COMPLETED = "completed"

# --------------------------------------------------------------------------- #
# Backoff strategies
# --------------------------------------------------------------------------- #

BACKOFF_FIXED = "fixed"
BACKOFF_EXPONENTIAL = "exponential"

# Defaults applied when a campaign's ``retry_config`` omits a field.
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_INTERVAL_MINUTES = 15
DEFAULT_BACKOFF_STRATEGY = BACKOFF_FIXED


def _normalize_outcome(outcome: str | None) -> str:
    """Canonicalise an outcome label.

    Telephony emits ``no-answer`` while the retry config uses ``no_answer``;
    normalise hyphens/case/whitespace so both map to the same key.
    """

    return (outcome or "").strip().lower().replace("-", "_").replace(" ", "_")


def is_retryable(outcome: str | None) -> bool:
    """True when ``outcome`` is a transient failure worth retrying."""

    return _normalize_outcome(outcome) in RETRYABLE_OUTCOMES


def resolve_retry_config(retry_config: dict | None) -> dict:
    """Normalise a campaign ``retry_config`` blob into engine settings.

    Accepts both the new schema (``retry_interval_minutes`` +
    ``backoff_strategy``) and the legacy one (``backoff_minutes``), falling
    back to module defaults for anything missing.
    """

    cfg = retry_config or {}

    try:
        max_attempts = int(cfg.get("max_attempts", DEFAULT_MAX_ATTEMPTS))
    except (TypeError, ValueError):
        max_attempts = DEFAULT_MAX_ATTEMPTS
    max_attempts = max(1, max_attempts)

    interval = cfg.get("retry_interval_minutes")
    if interval is None:
        # Back-compat: the original config used ``backoff_minutes``.
        interval = cfg.get("backoff_minutes", DEFAULT_RETRY_INTERVAL_MINUTES)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = DEFAULT_RETRY_INTERVAL_MINUTES
    interval = max(0, interval)

    strategy = cfg.get("backoff_strategy", DEFAULT_BACKOFF_STRATEGY)
    if strategy not in (BACKOFF_FIXED, BACKOFF_EXPONENTIAL):
        strategy = DEFAULT_BACKOFF_STRATEGY

    # Optional allow-list further restricting the global retryable set.
    retry_on = cfg.get("retry_on")
    if retry_on is not None:
        retry_on = {_normalize_outcome(o) for o in retry_on}

    return {
        "max_attempts": max_attempts,
        "retry_interval_minutes": interval,
        "backoff_strategy": strategy,
        "retry_on": retry_on,
    }


def backoff_delay_minutes(
    attempt_number: int,
    *,
    retry_interval_minutes: int,
    backoff_strategy: str,
) -> int:
    """Minutes to wait after ``attempt_number`` (the attempt that just ran).

    * ``fixed``       — always ``retry_interval_minutes``.
    * ``exponential`` — ``retry_interval_minutes * 2**(attempt_number - 1)``::

          attempt 1 -> +15   attempt 2 -> +30
          attempt 3 -> +60   attempt 4 -> +120
    """

    n = max(1, int(attempt_number))
    if backoff_strategy == BACKOFF_EXPONENTIAL:
        return retry_interval_minutes * (2 ** (n - 1))
    return retry_interval_minutes


def calculate_next_retry(
    attempt_number: int,
    retry_config: dict | None = None,
    *,
    now: datetime | None = None,
) -> datetime:
    """UTC instant of the next retry after ``attempt_number`` failed."""

    now = now or datetime.now(timezone.utc)
    cfg = resolve_retry_config(retry_config)
    delay = backoff_delay_minutes(
        attempt_number,
        retry_interval_minutes=cfg["retry_interval_minutes"],
        backoff_strategy=cfg["backoff_strategy"],
    )
    return now + timedelta(minutes=delay)


# --------------------------------------------------------------------------- #
# Per-execution outcome processing
# --------------------------------------------------------------------------- #

# Lifecycle ``status`` values mirrored from the scheduler/worker.
_EXEC_COMPLETED = "completed"
_EXEC_FAILED = "failed"

_MAX_HISTORY = 50


def _append_history(
    execution,
    *,
    attempt: int,
    outcome: str,
    failure_reason: str | None,
    ran_at: datetime,
    next_retry_at: datetime | None,
) -> None:
    """Append one attempt record to ``execution.context['retry_history']``.

    Stored on the existing ``context`` JSON column so in-place retries keep a
    full per-attempt trail without a separate table.
    """

    ctx = dict(execution.context or {})
    history = list(ctx.get("retry_history") or [])
    history.append(
        {
            "attempt_number": attempt,
            "outcome": outcome,
            "failure_reason": failure_reason,
            "ran_at": ran_at.isoformat(),
            "next_retry_at": (
                next_retry_at.isoformat() if next_retry_at else None
            ),
        }
    )
    ctx["retry_history"] = history[-_MAX_HISTORY:]
    execution.context = ctx


def process_outcome(
    db,
    execution,
    outcome: str,
    *,
    retry_config: dict | None,
    voicemail_config: dict | None = None,
    failure_reason: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
):
    """Apply a call ``outcome`` to ``execution`` and (maybe) schedule a retry.

    Decision table (for the attempt that just ran, ``n`` = ``attempt_number``):

    * non-retryable outcome           -> ``status=completed``, ``retry_status=completed``
    * retryable, no ``retry_config``  -> ``status=failed``,    ``retry_status=None`` (legacy terminal)
    * retryable, ``n >= max_attempts``-> ``status=failed``,    ``retry_status=exhausted``
    * retryable, attempts remain      -> ``status=failed``,    ``retry_status=scheduled``,
                                         ``attempt_number += 1``, ``next_retry_at`` set

    Voicemail policy: a ``voicemail`` outcome is retryable globally, but a
    campaign's ``voicemail_config`` overrides this — when ``retry_on_voicemail``
    is ``False`` a detected voicemail is treated as terminal (``completed``)
    rather than scheduling another dial. When ``voicemail_config`` is ``None``
    the legacy behaviour (voicemail is retryable) is preserved.
    """

    now = now or datetime.now(timezone.utc)
    norm = _normalize_outcome(outcome)
    execution.outcome = norm
    failed_attempt = int(execution.attempt_number or 1)

    cfg = resolve_retry_config(retry_config)
    retryable = norm in RETRYABLE_OUTCOMES
    if retryable and cfg["retry_on"] is not None:
        retryable = norm in cfg["retry_on"]

    # Campaign-level voicemail policy. Only applies to the voicemail outcome.
    if norm == "voicemail" and voicemail_config is not None:
        retryable = retryable and bool(
            voicemail_config.get("retry_on_voicemail", False)
        )

    next_retry_at: datetime | None = None

    if not retryable:
        # Terminal — success or explicit opt-out. Nothing more to dial.
        execution.status = _EXEC_COMPLETED
        execution.retry_status = RETRY_STATUS_COMPLETED
        execution.next_retry_at = None
        if failure_reason:
            execution.last_failure_reason = failure_reason
    else:
        execution.last_failure_reason = failure_reason or norm
        if retry_config is None:
            # No retry policy configured -> behave like the legacy worker.
            execution.status = _EXEC_FAILED
            execution.retry_status = None
            execution.next_retry_at = None
        elif failed_attempt >= cfg["max_attempts"]:
            execution.status = _EXEC_FAILED
            execution.retry_status = RETRY_STATUS_EXHAUSTED
            execution.next_retry_at = None
        else:
            next_retry_at = calculate_next_retry(
                failed_attempt, retry_config, now=now
            )
            execution.attempt_number = failed_attempt + 1
            execution.next_retry_at = next_retry_at
            execution.retry_status = RETRY_STATUS_SCHEDULED
            execution.status = _EXEC_FAILED

    _append_history(
        execution,
        attempt=failed_attempt,
        outcome=norm,
        failure_reason=execution.last_failure_reason,
        ran_at=now,
        next_retry_at=next_retry_at,
    )

    if commit:
        db.commit()
        db.refresh(execution)
    return execution
