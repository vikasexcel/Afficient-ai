"""API integration tests for the Google Calendar endpoints.

Tests use the real FastAPI app with a live DB (Postgres) but mock out
Google API calls so no real OAuth tokens are needed.

Covers:
- GET  /api/v1/calendar/status  (no integration → null)
- POST /api/v1/calendar/disconnect (no integration → disconnected=false)
- GET  /api/v1/calendar/availability (no integration → 404)
- GET  /api/v1/calendar/availability (with mocked integration → slots returned)
- POST /api/v1/calendar/book   (no integration → 404)
- POST /api/v1/calendar/book   (with mocked integration → event returned)
- GET  /auth/google             (auth required → 403 without token)
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.api


@contextmanager
def _override_calendar_svc(mock_svc):
    """Temporarily inject a mock CalendarService via FastAPI dependency override."""
    from main import app
    from modules.calendar.dependencies import get_calendar_service

    app.dependency_overrides[get_calendar_service] = lambda: mock_svc
    try:
        yield mock_svc
    finally:
        app.dependency_overrides.pop(get_calendar_service, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_calendar_integration(db, org_id: str):
    """Insert a fake CalendarIntegration row for tests that need one."""
    from modules.calendar.encryption import encrypt_token
    from modules.calendar.model import CalendarIntegration

    enc_access = encrypt_token("fake_access_token")
    enc_refresh = encrypt_token("fake_refresh_token")

    row = CalendarIntegration(
        organization_id=uuid.UUID(org_id),
        provider="google",
        calendar_email="org@example.com",
        access_token_enc=enc_access,
        refresh_token_enc=enc_refresh,
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        calendar_id="primary",
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


class TestCalendarStatus:
    def test_status_unauthenticated_returns_401(self, client):
        r = client.get("/api/v1/calendar/status")
        assert r.status_code == 401

    def test_status_no_integration_returns_null(self, client, unique_user):
        r = client.get(
            "/api/v1/calendar/status",
            headers={"Authorization": f"Bearer {unique_user['access_token']}"},
        )
        assert r.status_code == 200
        assert r.json() is None

    def test_status_with_integration_returns_object(self, client, unique_user):
        from database.session import SessionLocal

        db = SessionLocal()
        try:
            row = _insert_calendar_integration(db, unique_user["organization_id"])
            r = client.get(
                "/api/v1/calendar/status",
                headers={"Authorization": f"Bearer {unique_user['access_token']}"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data is not None
            assert data["provider"] == "google"
            assert data["calendar_email"] == "org@example.com"
            assert data["connected"] is True
        finally:
            # Cleanup
            db.query(
                __import__(
                    "modules.calendar.model",
                    fromlist=["CalendarIntegration"],
                ).CalendarIntegration
            ).filter_by(organization_id=unique_user["organization_id"]).delete()
            db.commit()
            db.close()


# ---------------------------------------------------------------------------
# Disconnect endpoint
# ---------------------------------------------------------------------------


class TestCalendarDisconnect:
    def test_disconnect_unauthenticated_returns_401(self, client):
        r = client.post("/api/v1/calendar/disconnect")
        assert r.status_code == 401

    def test_disconnect_no_integration_returns_false(self, client, unique_user):
        r = client.post(
            "/api/v1/calendar/disconnect",
            headers={"Authorization": f"Bearer {unique_user['access_token']}"},
        )
        assert r.status_code == 200
        assert r.json()["disconnected"] is False

    def test_disconnect_removes_integration(self, client, unique_user):
        from database.session import SessionLocal
        from modules.calendar.model import CalendarIntegration

        db = SessionLocal()
        try:
            _insert_calendar_integration(db, unique_user["organization_id"])
        finally:
            db.close()

        r = client.post(
            "/api/v1/calendar/disconnect",
            headers={"Authorization": f"Bearer {unique_user['access_token']}"},
        )
        assert r.status_code == 200
        assert r.json()["disconnected"] is True

        # Verify it's gone
        db = SessionLocal()
        try:
            row = (
                db.query(CalendarIntegration)
                .filter_by(organization_id=unique_user["organization_id"])
                .first()
            )
            assert row is None
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Availability endpoint
# ---------------------------------------------------------------------------


class TestCalendarAvailability:
    def test_availability_unauthenticated_returns_401(self, client):
        r = client.get("/api/v1/calendar/availability?date_iso=2026-06-20")
        assert r.status_code == 401

    def test_availability_no_integration_returns_404(self, client, unique_user):
        r = client.get(
            "/api/v1/calendar/availability",
            params={"date_iso": "2026-06-20"},
            headers={"Authorization": f"Bearer {unique_user['access_token']}"},
        )
        assert r.status_code == 404

    def test_availability_invalid_date_returns_400(self, client, unique_user):
        r = client.get(
            "/api/v1/calendar/availability",
            params={"date_iso": "not-a-date"},
            headers={"Authorization": f"Bearer {unique_user['access_token']}"},
        )
        assert r.status_code == 400

    def test_availability_with_mocked_integration_returns_slots(
        self, client, unique_user
    ):
        from modules.calendar.schema import FreeSlot

        mock_slots = [
            FreeSlot(
                start=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
                end=datetime(2026, 6, 20, 9, 30, tzinfo=timezone.utc),
                start_display="9:00 AM",
                duration_minutes=30,
            ),
            FreeSlot(
                start=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
                end=datetime(2026, 6, 20, 10, 30, tzinfo=timezone.utc),
                start_display="10:00 AM",
                duration_minutes=30,
            ),
        ]

        svc = MagicMock()
        svc.get_free_slots = AsyncMock(return_value=mock_slots)

        with _override_calendar_svc(svc):
            r = client.get(
                "/api/v1/calendar/availability",
                params={"date_iso": "2026-06-20", "tz": "UTC"},
                headers={"Authorization": f"Bearer {unique_user['access_token']}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert "slots" in data
        assert len(data["slots"]) == 2
        assert data["slots"][0]["start_display"] == "9:00 AM"


# ---------------------------------------------------------------------------
# Book endpoint
# ---------------------------------------------------------------------------


class TestCalendarBook:
    def test_book_unauthenticated_returns_401(self, client):
        r = client.post(
            "/api/v1/calendar/book",
            json={
                "slot_start_iso": "2026-06-20T09:00:00Z",
                "attendee_email": "x@x.com",
                "attendee_name": "X",
            },
        )
        assert r.status_code == 401

    def test_book_no_integration_returns_404(self, client, unique_user):
        r = client.post(
            "/api/v1/calendar/book",
            json={
                "slot_start_iso": "2026-06-20T09:00:00Z",
                "attendee_email": "x@x.com",
                "attendee_name": "X",
            },
            headers={"Authorization": f"Bearer {unique_user['access_token']}"},
        )
        assert r.status_code == 404

    def test_book_with_mocked_integration_returns_event(self, client, unique_user):
        from modules.calendar.schema import BookedEvent

        mock_event = BookedEvent(
            event_id="evt_test_123",
            meet_link="https://meet.google.com/aaa-bbb-ccc",
            html_link="https://calendar.google.com/event?eid=test",
            start_iso="2026-06-20T09:00:00+00:00",
            end_iso="2026-06-20T09:30:00+00:00",
            start_display="June 20 at 9:00 AM",
            title="Meeting",
        )

        svc = MagicMock()
        svc.book_meeting = AsyncMock(return_value=mock_event)

        with _override_calendar_svc(svc):
            r = client.post(
                "/api/v1/calendar/book",
                json={
                    "slot_start_iso": "2026-06-20T09:00:00Z",
                    "attendee_email": "lead@test.com",
                    "attendee_name": "Test Lead",
                    "title": "Demo Call",
                    "timezone": "UTC",
                },
                headers={"Authorization": f"Bearer {unique_user['access_token']}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["event_id"] == "evt_test_123"
        assert data["meet_link"] == "https://meet.google.com/aaa-bbb-ccc"

    def test_book_invalid_iso_returns_400(self, client, unique_user):
        svc = MagicMock()
        with _override_calendar_svc(svc):
            r = client.post(
                "/api/v1/calendar/book",
                json={
                    "slot_start_iso": "not-a-datetime",
                    "attendee_email": "x@x.com",
                    "attendee_name": "X",
                },
                headers={"Authorization": f"Bearer {unique_user['access_token']}"},
            )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# OAuth start endpoint (no real redirect — just verify it requires auth)
# ---------------------------------------------------------------------------


class TestCalendarOAuth:
    def test_oauth_start_without_token_returns_401(self, client):
        r = client.get("/auth/google")
        assert r.status_code == 401

    def test_oauth_start_with_token_returns_auth_url(self, client, unique_user):
        with patch(
            "google_auth_oauthlib.flow.Flow.from_client_config"
        ) as mock_from_config:
            mock_flow = MagicMock()
            mock_flow.authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth?mock=1",
                "state",
            )
            mock_from_config.return_value = mock_flow

            r = client.get(
                "/auth/google",
                params={"org_id": unique_user["organization_id"]},
                headers={"Authorization": f"Bearer {unique_user['access_token']}"},
            )

        assert r.status_code == 200
        data = r.json()
        assert "auth_url" in data
        assert "accounts.google.com" in data["auth_url"]
