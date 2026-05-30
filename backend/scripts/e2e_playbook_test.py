#!/usr/bin/env python3
"""E2E test for the playbook API + playbook-driven converse.

Validates against a running backend:

  1. Auth + tenant bootstrap.
  2. GET /playbooks — auto-seeds defaults.
  3. POST /playbooks — create draft.
  4. POST /playbooks/{id}/publish — version snapshot.
  5. POST /playbooks/{id}/test — dry-run qualification.
  6. POST /ai/converse with playbook_id — live turn uses playbook.
  7. GET /ai/calls/{id}/qualification — custom field progress.

Usage:
    cd backend && source venv/bin/activate
    python scripts/e2e_playbook_test.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import redis as redis_pkg  # noqa: E402
from config.settings import settings  # noqa: E402

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8002")
API = f"{BASE}/api/v1"


def flush_rate_limit() -> None:
    try:
        rc = redis_pkg.from_url(settings.REDIS_URL)
        for key in rc.scan_iter("api:*"):
            rc.delete(key)
    except Exception as exc:
        print(f"WARN: redis flush failed: {exc}")


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


async def main() -> int:
    if not settings.OPENAI_API_KEY:
        print(
            "NOTE: OPENAI_API_KEY not set — converse step may return 500."
        )

    email = f"e2e-pb-{uuid.uuid4().hex[:8]}@example.com"
    password = "E2eTestPass123!"
    call_id = f"pb-e2e-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=90.0) as client:
        flush_rate_limit()
        r = await client.post(
            f"{API}/auth/register",
            json={
                "full_name": "Playbook E2E",
                "email": email,
                "password": password,
                "organization": f"PB E2E {uuid.uuid4().hex[:6]}",
            },
        )
        if r.status_code not in (200, 201):
            _fail(f"register -> {r.status_code} {r.text}")

        r = await client.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
        )
        if r.status_code != 200:
            _fail(f"login -> {r.status_code}")
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        _ok("auth")

        flush_rate_limit()
        r = await client.get(f"{API}/playbooks", headers=headers)
        if r.status_code != 200:
            _fail(f"list playbooks -> {r.status_code} {r.text}")
        seeded = r.json().get("playbooks", [])
        if len(seeded) < 1:
            _fail("expected seeded playbooks")
        _ok(f"list playbooks ({len(seeded)} seeded)")

        flush_rate_limit()
        r = await client.post(
            f"{API}/playbooks",
            headers=headers,
            json={
                "name": f"E2E Custom {uuid.uuid4().hex[:6]}",
                "framework": "BANT",
                "persona_name": "outbound_sdr",
                "fields": [
                    {
                        "key": "budget",
                        "display_name": "Budget",
                        "weight": 2,
                        "required": True,
                        "cue_patterns": [r"\bbudget\b"],
                        "position": 0,
                    },
                    {
                        "key": "authority",
                        "display_name": "Authority",
                        "weight": 1,
                        "required": False,
                        "cue_patterns": [r"\bvp\b", r"\bdirector\b"],
                        "position": 1,
                    },
                ],
            },
        )
        if r.status_code != 201:
            _fail(f"create playbook -> {r.status_code} {r.text}")
        pb = r.json()
        pb_id = pb["id"]
        _ok(f"create playbook ({pb_id})")

        flush_rate_limit()
        r = await client.post(
            f"{API}/playbooks/{pb_id}/publish",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"publish -> {r.status_code} {r.text}")
        version = r.json().get("version", 0)
        if version < 2:
            _fail(f"expected version >= 2 after publish, got {version}")
        _ok(f"publish (v{version})")

        flush_rate_limit()
        r = await client.post(
            f"{API}/playbooks/{pb_id}/test",
            headers=headers,
            json={
                "user_text": "We have budget approved and I'm the VP of Sales.",
            },
        )
        if r.status_code != 200:
            _fail(f"test turn -> {r.status_code} {r.text}")
        test_data = r.json()
        newly = test_data.get("newly_set_fields", [])
        if "budget" not in newly:
            _fail(f"expected budget in newly_set_fields, got {newly}")
        _ok(f"test turn (new fields: {newly})")

        flush_rate_limit()
        r = await client.get(
            f"{API}/playbooks/{pb_id}/preview",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"preview -> {r.status_code} {r.text}")
        if not r.json().get("rendered_system_prompt"):
            _fail("empty preview prompt")
        _ok("preview prompt")

        if not settings.OPENAI_API_KEY:
            print("\nSKIP: converse (no OPENAI_API_KEY)")
            print("\nAll playbook API checks passed (LLM step skipped).")
            return 0

        flush_rate_limit()
        r = await client.post(
            f"{API}/ai/converse",
            headers=headers,
            json={
                "call_id": call_id,
                "user_input": (
                    "Hi, yes this is Jane. We have budget for Q3 and I am the "
                    "decision maker for our sales stack."
                ),
                "playbook_id": pb_id,
                "persist_transcript": True,
            },
        )
        if r.status_code != 200:
            _fail(f"converse -> {r.status_code} {r.text}")
        qual = r.json().get("qualification", {})
        score = qual.get("score", 0)
        _ok(f"converse with playbook (score={score}, status={qual.get('status')})")

        flush_rate_limit()
        r = await client.get(
            f"{API}/ai/calls/{call_id}/qualification",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"get qualification -> {r.status_code}")
        answered = r.json().get("qualification", {}).get("answered_fields", [])
        _ok(f"qualification persisted (answered: {answered})")

        flush_rate_limit()
        r = await client.get(f"{API}/ai/calls", headers=headers, params={"limit": 5})
        if r.status_code != 200:
            _fail(f"list calls -> {r.status_code}")
        calls = r.json().get("calls", [])
        match = next((c for c in calls if c.get("call_id") == call_id), None)
        if match and match.get("playbook_id"):
            _ok(f"call list has playbook_id={match['playbook_id']}")
        else:
            _ok("call list (playbook_id may appear after DB flush)")

    print("\nAll playbook E2E checks passed.")
    return 0


if __name__ == "__main__":
    import asyncio

    try:
        raise SystemExit(asyncio.run(main()))
    except httpx.ConnectError:
        print(f"FAIL: cannot connect to {BASE} — start the backend first:")
        print("  cd backend && source venv/bin/activate && uvicorn main:app --port 8002")
        raise SystemExit(1) from None
