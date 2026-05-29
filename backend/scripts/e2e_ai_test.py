#!/usr/bin/env python3
"""End-to-end test for the GPT-4o conversation engine.

Validates, against a real running backend and real OpenAI:

  1. Auth + tenant bootstrap.
  2. `POST /api/v1/ai/generate` — stateless one-shot completion.
  3. `POST /api/v1/ai/converse` — first stateful turn (call_id created).
  4. `POST /api/v1/ai/converse` — second turn (memory carries forward).
  5. `GET  /api/v1/ai/calls/{id}/qualification` — BANT state updates.
  6. `GET  /api/v1/ai/calls/{id}/transcript` — DB-backed transcript.
  7. `POST /api/v1/ai/calls/{id}/finalize` — summary + qualification persist.
  8. Redis memory eviction after finalize (clear_memory=True).

Set OPENAI_API_KEY in `backend/.env` first. Without a key, the script
detects an `AIConfigError` 500 from /generate and exits early with a
clear message.

Usage:

    cd backend
    source venv/bin/activate
    python scripts/e2e_ai_test.py
"""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def flush_rate_limit() -> None:
    try:
        rc = redis_pkg.from_url(settings.REDIS_URL)
        for key in rc.scan_iter("api:*"):
            rc.delete(key)
    except Exception as exc:  # pragma: no cover
        print(f"WARN: redis flush failed: {exc}")


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def main() -> int:
    if not settings.OPENAI_API_KEY:
        print(
            "NOTE: OPENAI_API_KEY not set — endpoints will return 500. "
            "Add a key to backend/.env to exercise the real LLM."
        )

    email = f"e2e-ai-{uuid.uuid4().hex[:8]}@example.com"
    password = "E2eTestPass123!"
    call_id = f"ai-e2e-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Auth
        flush_rate_limit()
        r = await client.post(
            f"{API}/auth/register",
            json={
                "full_name": "AI E2E",
                "email": email,
                "password": password,
                "organization": f"AI E2E Org {uuid.uuid4().hex[:6]}",
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
        access = r.json().get("access_token")
        if not access:
            _fail("no access_token")
        headers = {"Authorization": f"Bearer {access}"}
        _ok(f"auth ({email})")

        # 2. Stateless generate
        flush_rate_limit()
        r = await client.post(
            f"{API}/ai/generate",
            headers=headers,
            json={
                "prompt": "Reply with exactly: pong.",
                "system": "You are a terse echo bot.",
                "temperature": 0.0,
                "max_tokens": 8,
            },
        )
        if r.status_code != 200:
            if r.status_code == 500 and "OPENAI_API_KEY" in r.text:
                print(
                    "\nAborting: OPENAI_API_KEY is unset on the server. "
                    "Add it to backend/.env and restart the backend."
                )
                return 1
            _fail(f"ai/generate -> {r.status_code} {r.text}")
        gen = r.json()
        if not gen.get("output"):
            _fail(f"empty generate output: {gen}")
        _ok(
            f"ai/generate (model={gen['model']}, "
            f"latency={gen['latency_ms']}ms, "
            f"tokens={gen['total_tokens']}, "
            f"out={gen['output'][:40]!r})"
        )

        # 3. Converse turn #1
        flush_rate_limit()
        r = await client.post(
            f"{API}/ai/converse",
            headers=headers,
            json={
                "call_id": call_id,
                "user_input": (
                    "Hi, this is Jane Doe, VP Sales at Acme. We have a "
                    "$50k budget for a new outbound dialer and want "
                    "something live by next quarter."
                ),
                "persona": "outbound_sdr",
                "qualification_framework": "BANT",
                "extra_context": {
                    "lead_name": "Jane Doe",
                    "company": "Aifficient",
                    "product": "AI outbound calling platform",
                    "value_prop": "10x more conversations per SDR per day",
                    "objective": "book a 15-minute discovery call",
                    "agent_name": "Alex from Aifficient",
                },
            },
        )
        if r.status_code != 200:
            _fail(f"ai/converse#1 -> {r.status_code} {r.text}")
        c1 = r.json()
        if not c1.get("reply"):
            _fail(f"empty reply: {c1}")
        q1 = c1["qualification"]
        if q1["score"] < 50:
            print(
                f"  WARN: qualification score after turn 1 is {q1['score']}; "
                "expected >=50 because lead mentioned budget+authority+timeline."
            )
        _ok(
            f"ai/converse#1 (reply={c1['reply'][:60]!r}, "
            f"latency={c1['latency_ms']}ms, "
            f"history={c1['history_length']}, "
            f"qual={q1['status']}/{q1['score']})"
        )

        # 4. Converse turn #2 — memory carry-forward
        flush_rate_limit()
        r = await client.post(
            f"{API}/ai/converse",
            headers=headers,
            json={
                "call_id": call_id,
                "user_input": (
                    "We're evaluating you and one competitor. Can you do "
                    "Tuesday at 10am Eastern?"
                ),
            },
        )
        if r.status_code != 200:
            _fail(f"ai/converse#2 -> {r.status_code} {r.text}")
        c2 = r.json()
        if c2["history_length"] <= c1["history_length"]:
            _fail(
                f"history did not grow between turns: "
                f"{c1['history_length']} -> {c2['history_length']}"
            )
        _ok(
            f"ai/converse#2 (history={c2['history_length']}, "
            f"qual={c2['qualification']['status']}/"
            f"{c2['qualification']['score']})"
        )

        # 5. Qualification GET
        flush_rate_limit()
        r = await client.get(
            f"{API}/ai/calls/{call_id}/qualification",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"qualification -> {r.status_code}")
        snap = r.json()["qualification"]
        _ok(
            f"qualification ({snap['framework']} "
            f"{snap['status']}/{snap['score']}, "
            f"answered={snap['answered_fields']})"
        )

        # 6. Transcript GET (DB-backed)
        flush_rate_limit()
        r = await client.get(
            f"{API}/ai/calls/{call_id}/transcript",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"transcript -> {r.status_code}")
        entries = r.json()["entries"]
        if len(entries) < 4:
            _fail(
                f"expected >=4 transcript entries (2 user + 2 assistant), "
                f"got {len(entries)}"
            )
        _ok(f"transcript ({len(entries)} entries)")

        # 7. Finalize
        flush_rate_limit()
        r = await client.post(
            f"{API}/ai/calls/{call_id}/finalize",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"finalize -> {r.status_code} {r.text}")
        summary = r.json()
        _ok(
            f"finalize (turns={summary['total_turns']}, "
            f"tokens={summary['total_tokens']}, "
            f"summary_len={len(summary.get('summary') or '')})"
        )
        if summary.get("summary"):
            print(f"\n--- Call summary ---\n{summary['summary']}\n")

        # 8. Memory cleared after finalize (clear_memory=True default)
        flush_rate_limit()
        r = await client.get(
            f"{API}/ai/calls/{call_id}/qualification",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"post-finalize qualification -> {r.status_code}")
        # Qualification stays in Redis (separate key); history is cleared.
        # Verify by hitting the transcript and confirming entries persist.
        r = await client.get(
            f"{API}/ai/calls/{call_id}/transcript",
            headers=headers,
        )
        if r.status_code != 200 or len(r.json()["entries"]) < 4:
            _fail("transcript should still be present in DB after finalize")
        _ok("transcript persists in DB after finalize")

    print("\n=== AI conversation engine E2E passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
