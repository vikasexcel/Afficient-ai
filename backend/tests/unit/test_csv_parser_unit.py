"""Unit tests for :mod:`modules.leads.csv_parser`.

The parser is dependency-free so these tests are pure-Python.
"""

from __future__ import annotations

import pytest

from modules.leads.csv_parser import (
    annotate_duplicates,
    detect_columns,
    normalize_phone,
    parse_csv_text,
    validate_row,
)


pytestmark = pytest.mark.unit


def test_normalize_phone_strips_non_digits():
    assert normalize_phone("+1 (415) 555-1212") == "14155551212"
    assert normalize_phone("") == ""
    assert normalize_phone("abc") == ""


def test_detect_columns_recognises_canonical_headers():
    mapping = detect_columns(["Name", "Email", "Phone"])
    assert mapping["name"] == "Name"
    assert mapping["email"] == "Email"
    assert mapping["phone"] == "Phone"


def test_detect_columns_recognises_synonyms():
    mapping = detect_columns(
        ["Full Name", "Work Email", "Mobile Number", "Company"]
    )
    assert mapping["name"] == "Full Name"
    assert mapping["email"] == "Work Email"
    assert mapping["phone"] == "Mobile Number"
    assert mapping["company"] == "Company"


def test_detect_columns_returns_none_for_missing():
    mapping = detect_columns(["First", "Last"])
    assert mapping["email"] is None
    assert mapping["phone"] is None


def test_parse_csv_text_returns_rows_and_headers():
    text = "name,email,phone\nJane,jane@example.com,+14155551212\n"
    rows, headers = parse_csv_text(text)
    assert headers == ["name", "email", "phone"]
    assert rows == [
        {"name": "Jane", "email": "jane@example.com", "phone": "+14155551212"}
    ]


def test_parse_csv_text_skips_blank_rows():
    text = "name,email,phone\nJane,j@e.com,+14155551212\n,,\nJohn,jo@e.com,+14155551313\n"
    rows, _ = parse_csv_text(text)
    assert [r["name"] for r in rows] == ["Jane", "John"]


def test_parse_csv_text_raises_on_empty_input():
    with pytest.raises(ValueError, match="empty"):
        parse_csv_text("")


def test_validate_row_flags_invalid_email_but_keeps_valid_phone():
    rows, headers = parse_csv_text(
        "name,email,phone\nJane,not-an-email,+14155551212\n"
    )
    mapping = detect_columns(headers)
    out = validate_row(row_number=2, raw=rows[0], columns=mapping)
    assert out["status"] == "invalid"
    assert any("email" in e.lower() for e in out["errors"])


def test_validate_row_requires_phone():
    rows, headers = parse_csv_text("name,email,phone\nJane,j@e.com,\n")
    out = validate_row(row_number=2, raw=rows[0], columns=detect_columns(headers))
    assert out["status"] == "invalid"
    assert any("phone" in e.lower() for e in out["errors"])


def test_validate_row_passes_through_custom_fields():
    rows, headers = parse_csv_text(
        "name,phone,custom\nJane,+14155551212,extra-value\n"
    )
    out = validate_row(row_number=2, raw=rows[0], columns=detect_columns(headers))
    assert out["status"] == "valid"
    assert out["custom_fields"] == {"custom": "extra-value"}


def test_annotate_duplicates_flags_within_file_and_against_db():
    rows, headers = parse_csv_text(
        "name,email,phone\n"
        "Jane,jane@example.com,+14155551212\n"
        "John,john@example.com,+1 (415) 555-1212\n"
        "Mary,mary@example.com,+14155559999\n"
    )
    columns = detect_columns(headers)
    parsed = [
        validate_row(row_number=i + 2, raw=r, columns=columns)
        for i, r in enumerate(rows)
    ]
    out = annotate_duplicates(
        parsed,
        existing_normalized_phones={"14155559999"},
    )
    statuses = [r["status"] for r in out]
    # Jane (first), John (in-file dup), Mary (existing-in-db dup).
    assert statuses[0] == "valid"
    assert statuses[1] == "duplicate"
    assert statuses[2] == "duplicate"
