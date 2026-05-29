#!/usr/bin/env python3
"""HTTP TTS latency benchmark.

Hits ``POST /api/v1/tts/speak`` N times against a running backend and
reports p50/p95 for every per-stage timing surfaced in ``SpeakResponse``.
Useful for verifying that the latency you see in production matches the
in-process numbers (any large delta is FastAPI / network / serialization
overhead).

Usage:

    cd backend
    source venv/bin/activate
    python scripts/bench_tts_http.py --iters 5 --base http://127.0.0.1:8002

The script registers a throwaway user, creates a LiveKit room, runs the
benchmark, then tears the room down.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import uuid

import httpx


def _pct(values: list[int], p: float) -> int:
    if not values:
        return 0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round((p / 100.0) * (len(values) - 1)))))
    return values[k]


def _row(label: str, values: list[int]) -> str:
    return (
        f"{label:<22} "
        f"p50={_pct(values, 50):>5} ms  "
        f"p95={_pct(values, 95):>5} ms  "
        f"min={min(values):>5} ms  "
        f"max={max(values):>5} ms  "
        f"mean={int(statistics.mean(values)):>5} ms"
    )


SAMPLE_TEXTS = [
    "Hello, this is a quick latency check.",
    "Thanks for taking my call today, I will keep this brief.",
    "We help teams run AI-powered outbound campaigns with real-time voice.",
]


async def _run(base: str, iters: int, text: str | None) -> int:
    api = f"{base.rstrip('/')}/api/v1"
    email = f"bench-{uuid.uuid4().hex[:8]}@example.com"
    password = "BenchPass123!"
    room_name = f"bench-http-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(f"{api}/health")
        if r.status_code != 200:
            print(f"FAIL health: {r.status_code} {r.text}")
            return 1

        r = await client.post(
            f"{api}/auth/register",
            json={
                "full_name": "Bench User",
                "email": email,
                "password": password,
                "organization": f"Bench {uuid.uuid4().hex[:6]}",
            },
        )
        if r.status_code not in (200, 201):
            print(f"FAIL register: {r.status_code} {r.text}")
            return 1

        r = await client.post(
            f"{api}/auth/login",
            json={"email": email, "password": password},
        )
        if r.status_code != 200:
            print(f"FAIL login: {r.status_code} {r.text}")
            return 1
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = await client.post(
            f"{api}/livekit/rooms",
            headers=headers,
            json={"name": room_name, "max_participants": 4},
        )
        if r.status_code not in (200, 201):
            print(f"FAIL create room: {r.status_code} {r.text}")
            return 1

        per_stage: dict[str, list[int]] = {}
        try:
            for i in range(iters):
                utterance = text or SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)]
                print(f"\n[{i+1}/{iters}] /tts/speak: {utterance!r}")
                r = await client.post(
                    f"{api}/tts/speak",
                    headers=headers,
                    json={"room": room_name, "text": utterance, "wait": True},
                )
                if r.status_code != 200:
                    print(f"  FAIL: {r.status_code} {r.text}")
                    continue
                body = r.json()
                stages = body.get("stages") or {}
                stages.setdefault("total_ms", body.get("duration_ms", 0))
                for k, v in stages.items():
                    per_stage.setdefault(k, []).append(int(v))
                print(
                    f"  total={body.get('duration_ms')} ms  "
                    f"ttfb={stages.get('ttfb_ms')} ms  "
                    f"first_frame={stages.get('first_frame_pub_ms')} ms  "
                    f"playout={stages.get('playout_wait_ms')} ms  "
                    f"bytes={body.get('bytes_streamed')}"
                )
        finally:
            await client.delete(
                f"{api}/livekit/rooms/{room_name}", headers=headers
            )

    if not per_stage:
        print("no results")
        return 1

    print("\n=== per-stage latency (HTTP /tts/speak) ===")
    preferred = [
        "token_mint_ms",
        "connect_ms",
        "ttfb_ms",
        "first_frame_pub_ms",
        "stream_end_ms",
        "playout_wait_ms",
        "disconnect_ms",
        "total_ms",
    ]
    ordered = [k for k in preferred if k in per_stage] + [
        k for k in per_stage if k not in preferred
    ]
    for k in ordered:
        print(_row(k, per_stage[k]))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=os.environ.get("BENCH_BASE_URL", "http://127.0.0.1:8002"),
    )
    parser.add_argument("--iters", type=int, default=5)
    parser.add_argument("--text", type=str, default=None)
    args = parser.parse_args()
    return asyncio.run(_run(args.base, args.iters, args.text))


if __name__ == "__main__":
    sys.exit(main())
