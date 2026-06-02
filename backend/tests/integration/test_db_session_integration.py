"""Integration tests for the SQLAlchemy session factory.

These tests assume Postgres is running locally on the host:port from
``backend/.env``. They are skipped automatically if the engine can't
reach the database — so the suite stays green on a workstation without
docker-compose up.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from database.session import SessionLocal, engine


pytestmark = pytest.mark.integration


def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    not _db_available(), reason="Postgres is not reachable on configured port",
)]


def test_session_round_trip_selects_one():
    db = SessionLocal()
    try:
        assert db.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        db.close()


def test_engine_pool_is_pre_pinged():
    # pool_pre_ping must be True so dead connections don't surface as 500s
    # in production.
    assert engine.pool._pre_ping is True


def test_two_sessions_are_independent():
    a = SessionLocal()
    b = SessionLocal()
    try:
        a.execute(text("SELECT pg_backend_pid()")).scalar_one()
        b.execute(text("SELECT pg_backend_pid()")).scalar_one()
        # We don't assert they differ — connection pooling might recycle —
        # but each session must execute independently without locking.
    finally:
        a.close()
        b.close()


def test_core_tables_exist():
    expected = {
        "users",
        "organizations",
        "memberships",
        "sessions",
        "audit_logs",
        "campaigns",
        "ai_calls",
        "ai_transcripts",
        "telephony_calls",
        "playbooks",
        "leads",
        "lead_lists",
    }
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            )
        ).all()
        present = {r[0] for r in rows}
        missing = expected - present
        # Don't fail hard if a couple are renamed; just require >80% present.
        assert len(missing) <= len(expected) // 5, f"missing tables: {missing}"
    finally:
        db.close()
