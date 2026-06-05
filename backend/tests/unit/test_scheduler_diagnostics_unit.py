"""Unit tests for campaign scheduler diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from modules.campaign.scheduler_diagnostics import scheduler_status


@pytest.mark.unit
def test_scheduler_status_all_healthy():
    db = MagicMock()
    db.execute.return_value.all.return_value = [("queued", 2), ("running", 1)]

    with (
        patch(
            "modules.campaign.scheduler_diagnostics._redis_ping",
            return_value=(True, None),
        ),
        patch(
            "modules.campaign.scheduler_diagnostics._worker_running",
            return_value=True,
        ),
        patch(
            "modules.campaign.scheduler_diagnostics._beat_running",
            return_value=True,
        ),
        patch(
            "modules.campaign.scheduler_diagnostics._last_scheduler_tick",
            return_value="2026-06-05T12:00:00+00:00",
        ),
        patch(
            "modules.campaign.scheduler_diagnostics._parse_iso",
            return_value=__import__("datetime").datetime(
                2026, 6, 5, 12, 0, tzinfo=__import__("datetime").timezone.utc
            ),
        ),
    ):
        out = scheduler_status(db)

    assert out["scheduler_online"] is True
    assert out["queued_executions"] == 2
    assert out["queued_execution_count"] == 2
    assert out["active_executions"] == 1
    assert out["worker_running"] is True
    assert out["beat_running"] is True
    assert out["last_tick"] == "2026-06-05T12:00:00+00:00"


@pytest.mark.unit
def test_scheduler_status_offline_when_no_worker():
    db = MagicMock()
    db.execute.return_value.all.return_value = [("queued", 5)]

    with (
        patch(
            "modules.campaign.scheduler_diagnostics._redis_ping",
            return_value=(True, None),
        ),
        patch(
            "modules.campaign.scheduler_diagnostics._worker_running",
            return_value=False,
        ),
        patch(
            "modules.campaign.scheduler_diagnostics._beat_running",
            return_value=True,
        ),
        patch(
            "modules.campaign.scheduler_diagnostics._last_scheduler_tick",
            return_value=None,
        ),
    ):
        out = scheduler_status(db)

    assert out["scheduler_online"] is False
    assert "worker" in out["message"].lower()
    assert out["queued_executions"] == 5
