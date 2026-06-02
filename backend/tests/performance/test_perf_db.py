"""Sustained-load tests against Postgres."""

from __future__ import annotations

import concurrent.futures as cf
import os
import time

import pytest
import redis
from sqlalchemy import text

from config.settings import settings
from database.session import SessionLocal, engine
from tests._support.benchmark import get_recorder


def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.performance,
    pytest.mark.integration,
    pytest.mark.skipif(not _db_available(), reason="Postgres is not reachable"),
]


CONCURRENCY = int(os.environ.get("PERF_DB_CONCURRENCY", "8"))
REQUESTS = int(os.environ.get("PERF_DB_REQUESTS", "80"))


def _one_select_one() -> tuple[bool, float]:
    started = time.perf_counter()
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1")).scalar_one()
        return True, (time.perf_counter() - started) * 1000.0
    except Exception:
        return False, (time.perf_counter() - started) * 1000.0
    finally:
        db.close()


def test_db_sustained_select_one():
    """Burst N concurrent sessions to verify the pool keeps up."""

    rec = get_recorder()
    pool = cf.ThreadPoolExecutor(max_workers=CONCURRENCY)
    try:
        futures = [pool.submit(_one_select_one) for _ in range(REQUESTS)]
        for f in cf.as_completed(futures):
            ok, lat = f.result()
            rec.record(
                category="perf",
                name="db SELECT 1 (concurrent)",
                latency_ms=lat,
                success=ok,
                metadata={
                    "concurrency": CONCURRENCY,
                    "requests": REQUESTS,
                },
            )
    finally:
        pool.shutdown(wait=True)
