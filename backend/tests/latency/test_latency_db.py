"""Latency benchmarks for the SQLAlchemy session + common queries.

Skipped automatically when Postgres is unreachable.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text

from database.session import SessionLocal, engine
from modules.auth.audit_model import AuditLog
from modules.auth.membership_model import Membership
from modules.auth.model import User
from modules.auth.organization_model import Organization
from tests._support.benchmark import measure


def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.latency,
    pytest.mark.integration,
    pytest.mark.skipif(not _db_available(), reason="Postgres is not reachable"),
]


ITERATIONS = int(os.environ.get("BENCH_DB_ITERATIONS", "30"))


def test_latency_db_select_one():
    for _ in range(ITERATIONS):
        with measure("db", "SELECT 1"):
            db = SessionLocal()
            try:
                db.execute(text("SELECT 1")).scalar_one()
            finally:
                db.close()


def test_latency_db_user_lookup(unique_user):
    user_id = unique_user["user_id"]
    for _ in range(ITERATIONS):
        with measure("db", "SELECT user by id"):
            db = SessionLocal()
            try:
                row = db.execute(
                    select(User).where(User.id == uuid.UUID(user_id))
                ).scalar_one_or_none()
                assert row is not None
            finally:
                db.close()


def test_latency_db_membership_join(unique_user):
    user_id = unique_user["user_id"]
    for _ in range(ITERATIONS):
        with measure("db", "JOIN membership × organization"):
            db = SessionLocal()
            try:
                row = db.execute(
                    select(Membership, Organization)
                    .join(Organization, Organization.id == Membership.organization_id)
                    .where(Membership.user_id == uuid.UUID(user_id))
                    .limit(1)
                ).first()
                assert row is not None
            finally:
                db.close()


def test_latency_db_audit_pagination(unique_user, auth_headers, client):
    # Generate a couple of audit rows to make the query non-trivial.
    for _ in range(3):
        client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": unique_user["refresh_token"]},
        )
    for _ in range(ITERATIONS):
        with measure("db", "SELECT audit_logs ORDER BY created_at"):
            db = SessionLocal()
            try:
                db.execute(
                    select(AuditLog)
                    .where(AuditLog.user_id == uuid.UUID(unique_user["user_id"]))
                    .order_by(AuditLog.created_at.desc())
                    .limit(50)
                ).scalars().all()
            finally:
                db.close()


def test_latency_db_session_open_close():
    """Bare session open + close — measures pool acquisition overhead."""

    for _ in range(ITERATIONS):
        with measure("db", "Session open+close"):
            db = SessionLocal()
            db.close()
