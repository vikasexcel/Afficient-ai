"""CSV parsing + per-row validation for lead uploads.

Kept dependency-free (stdlib ``csv``) and pure so the same logic can be
exercised from tests without touching FastAPI or SQLAlchemy.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Iterable


# RFC-ish; good enough for upload-time triage. We let pydantic's EmailStr
# tighten the screws at commit time.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Accept loose phone formatting (parens, dashes, spaces, leading +).
# We normalize by stripping everything except digits, then require 7-15
# digits (E.164 max is 15, anything under 7 is almost certainly garbage).
_PHONE_ALLOWED_RE = re.compile(r"^[+\d\s().\-]+$")


# Column synonyms — the FE/UX lets users drop any CSV with reasonable
# headers and we'll guess the mapping. Lowercase + stripped on both sides.
_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": (
        "name",
        "full name",
        "full_name",
        "contact",
        "contact name",
        "lead",
        "lead name",
    ),
    "email": ("email", "email address", "e-mail", "work email"),
    "phone": (
        "phone",
        "phone number",
        "mobile",
        "mobile number",
        "cell",
        "contact number",
        "tel",
        "telephone",
    ),
    "company": ("company", "organization", "organisation", "account", "employer"),
    "industry": ("industry", "vertical", "sector"),
    "location": ("location", "city", "country", "region"),
    "tags": ("tags", "labels"),
}


def normalize_phone(raw: str) -> str:
    """Return only the digits in ``raw``; ``""`` if nothing usable."""
    return re.sub(r"\D", "", raw or "")


def detect_columns(headers: list[str]) -> dict[str, str | None]:
    """Map our canonical column ids to the CSV's actual header names."""

    lowered = {h.strip().lower(): h for h in headers}
    mapping: dict[str, str | None] = {}
    for canonical, synonyms in _COLUMN_SYNONYMS.items():
        match: str | None = None
        for syn in synonyms:
            if syn in lowered:
                match = lowered[syn]
                break
        mapping[canonical] = match
    return mapping


def _value(row: dict[str, str], header: str | None) -> str:
    if not header:
        return ""
    val = row.get(header)
    if val is None:
        return ""
    return val.strip()


def parse_csv_text(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """Return (rows, headers). Raises ``ValueError`` if the CSV is empty
    or has no header row."""

    if not text.strip():
        raise ValueError("CSV is empty")

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    if not headers:
        raise ValueError("CSV is missing a header row")

    rows: list[dict[str, str]] = []
    for row in reader:
        if all((v or "").strip() == "" for v in row.values()):
            continue
        rows.append(row)
    return rows, headers


def validate_row(
    *,
    row_number: int,
    raw: dict[str, str],
    columns: dict[str, str | None],
) -> dict:
    """Return a ``UploadParsedRow``-compatible dict for a single row."""

    name = _value(raw, columns["name"])
    email = _value(raw, columns["email"])
    phone = _value(raw, columns["phone"])
    company = _value(raw, columns["company"]) or None
    industry = _value(raw, columns["industry"]) or None
    location = _value(raw, columns["location"]) or None

    tags_raw = _value(raw, columns["tags"])
    tags = (
        [t.strip() for t in tags_raw.split(",") if t.strip()]
        if tags_raw
        else None
    )

    errors: list[str] = []

    if not name:
        errors.append("name is required")
    elif len(name) > 255:
        errors.append("name is too long (max 255 chars)")

    if not phone:
        errors.append("phone is required")
    else:
        if not _PHONE_ALLOWED_RE.match(phone):
            errors.append("phone contains invalid characters")
        normalized = normalize_phone(phone)
        if len(normalized) < 7:
            errors.append("phone is too short (need at least 7 digits)")
        elif len(normalized) > 15:
            errors.append("phone is too long (max 15 digits, E.164)")

    if email and not _EMAIL_RE.match(email):
        errors.append("email is not a valid address")

    # Stash any extra columns the user uploaded as custom_fields so we
    # don't lose data the schema doesn't model.
    known_headers = {h for h in columns.values() if h}
    custom_fields: dict[str, str] = {}
    for k, v in raw.items():
        if not k or k in known_headers:
            continue
        cleaned = (v or "").strip()
        if cleaned:
            custom_fields[k.strip()] = cleaned

    return {
        "row_number": row_number,
        "name": name or None,
        "email": email or None,
        "phone": phone or None,
        "company": company,
        "industry": industry,
        "location": location,
        "tags": tags,
        "custom_fields": custom_fields or None,
        "status": "invalid" if errors else "valid",
        "errors": errors,
    }


def annotate_duplicates(
    rows: Iterable[dict],
    *,
    existing_normalized_phones: set[str],
) -> list[dict]:
    """Mark rows duplicate-against-file or duplicate-against-db.

    Rows already classified ``invalid`` are left untouched.
    """

    seen_in_file: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if row["status"] == "invalid":
            out.append(row)
            continue

        normalized = normalize_phone(row.get("phone") or "")
        if not normalized:
            out.append(row)
            continue

        if normalized in seen_in_file:
            row = {
                **row,
                "status": "duplicate",
                "errors": [*row["errors"], "duplicate phone in this CSV"],
            }
        elif normalized in existing_normalized_phones:
            row = {
                **row,
                "status": "duplicate",
                "errors": [
                    *row["errors"],
                    "phone already exists in your workspace",
                ],
            }
        else:
            seen_in_file.add(normalized)

        out.append(row)
    return out
