"""CSV-parser throughput. Pure-Python — no DB / Redis."""

from __future__ import annotations

import io
import os
import time

import pytest

from modules.leads.csv_parser import (
    annotate_duplicates,
    detect_columns,
    parse_csv_text,
    validate_row,
)
from tests._support.benchmark import get_recorder


pytestmark = pytest.mark.performance


ROWS = int(os.environ.get("PERF_CSV_ROWS", "1000"))


def _make_csv(rows: int) -> str:
    buf = io.StringIO()
    buf.write("name,email,phone,company\n")
    for i in range(rows):
        buf.write(
            f"Lead {i},lead{i}@example.com,+1415555{i % 10000:04d},Acme {i}\n"
        )
    return buf.getvalue()


def test_csv_parse_throughput():
    rec = get_recorder()
    text = _make_csv(ROWS)
    t0 = time.perf_counter()
    parsed_rows, headers = parse_csv_text(text)
    parse_ms = (time.perf_counter() - t0) * 1000.0

    columns = detect_columns(headers)
    t0 = time.perf_counter()
    validated = [
        validate_row(row_number=i + 2, raw=r, columns=columns)
        for i, r in enumerate(parsed_rows)
    ]
    validate_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    annotate_duplicates(validated, existing_normalized_phones=set())
    dedupe_ms = (time.perf_counter() - t0) * 1000.0

    rec.record(
        category="perf",
        name=f"csv parse_csv_text ({ROWS} rows)",
        latency_ms=parse_ms,
        success=True,
        metadata={"rows": ROWS},
    )
    rec.record(
        category="perf",
        name=f"csv validate_row × {ROWS}",
        latency_ms=validate_ms,
        success=True,
        metadata={"rows": ROWS, "rows_per_s": int(ROWS / max(validate_ms / 1000.0, 1e-9))},
    )
    rec.record(
        category="perf",
        name=f"csv annotate_duplicates × {ROWS}",
        latency_ms=dedupe_ms,
        success=True,
        metadata={"rows": ROWS},
    )

    assert len(validated) == ROWS
