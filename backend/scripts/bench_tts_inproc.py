#!/usr/bin/env python3
"""In-process TTS latency benchmark.

Drives :class:`TTSStreamer` directly (no HTTP, no FastAPI) and reports
per-stage latency for N iterations of the one-shot path:

    token mint -> LiveKit connect -> ElevenLabs TTFB -> first published
    frame -> stream end -> playout drain -> disconnect -> total

Why bother:

* Isolates each stage so you can see whether the bottleneck is the TTS
  provider, the LiveKit publish path, the connect/teardown cost, or the
  playout drain.
* Establishes a baseline you can re-run after changes (e.g. switching to
  the long-lived ``open_session`` path).

Usage:

    cd backend
    source venv/bin/activate
    python scripts/bench_tts_inproc.py --iters 5

Requires the LiveKit dev server, ElevenLabs creds, and the env vars from
``backend/.env`` (the script bootstraps the same settings as the FastAPI
app, so make sure you run it from ``backend/`` or have ``.env`` reachable).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import uuid
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parent.parent
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.livekit.schema import CreateRoomRequest  # noqa: E402
from modules.livekit.service import LiveKitService  # noqa: E402
from modules.tts.elevenlabs_client import ElevenLabsTTS  # noqa: E402
from modules.tts.streamer import SpeakStats, TTSStreamer  # noqa: E402


SAMPLE_TEXTS = [
    "Hello, this is a quick latency check.",
    "Thanks for taking my call today, I will keep this brief.",
    "We help teams run AI-powered outbound campaigns with real-time voice.",
]


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


async def _run(iters: int, text: str | None) -> int:
    tts = ElevenLabsTTS()
    livekit = LiveKitService()
    streamer = TTSStreamer(tts=tts, livekit=livekit)

    room_name = f"bench-{uuid.uuid4().hex[:8]}"
    print(f"creating room: {room_name}")
    await livekit.create_room(CreateRoomRequest(name=room_name, max_participants=4))

    results: list[SpeakStats] = []
    try:
        for i in range(iters):
            utterance = text or SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)]
            print(f"\n[{i+1}/{iters}] speaking: {utterance!r}")
            stats = await streamer.speak_into_room(room=room_name, text=utterance)
            results.append(stats)
            print(
                f"  total={stats.total_ms} ms  "
                f"ttfb={stats.ttfb_ms} ms  "
                f"first_frame={stats.first_frame_pub_ms} ms  "
                f"playout={stats.playout_wait_ms} ms  "
                f"bytes={stats.bytes_streamed}"
            )
    finally:
        try:
            await livekit.delete_room(room_name)
        except Exception as exc:  # pragma: no cover - cleanup best-effort
            print(f"warn: delete_room failed: {exc}")
        await livekit.aclose()

    if not results:
        print("no results")
        return 1

    print("\n=== per-stage latency (in-process, one-shot path) ===")
    fields = [
        ("token_mint_ms", "token_mint"),
        ("connect_ms", "lk_connect"),
        ("ttfb_ms", "el_ttfb"),
        ("first_frame_pub_ms", "first_frame_pub"),
        ("stream_end_ms", "el_stream_end"),
        ("playout_wait_ms", "playout_wait"),
        ("disconnect_ms", "lk_disconnect"),
        ("total_ms", "TOTAL"),
    ]
    for attr, label in fields:
        values = [getattr(s, attr) for s in results]
        print(_row(label, values))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iters", type=int, default=5)
    parser.add_argument(
        "--text",
        type=str,
        default=None,
        help="Override utterance (default: rotating sample texts).",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.iters, args.text))


if __name__ == "__main__":
    sys.exit(main())
