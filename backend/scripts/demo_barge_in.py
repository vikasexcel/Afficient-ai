#!/usr/bin/env python3
"""Demonstrate barge-in: STT speech_started cancels in-flight TTS.

Flow:
    1. Open a LiveKit room with both a TTS publisher and an STT subscriber
       in a long-lived ``TTSSession`` / ``STTSession``.
    2. Kick off a long utterance via ``TTSSession.speak``.
    3. Listen on the STT event stream; on the first ``SPEECH_STARTED`` event
       (i.e. a "user" started talking), call ``TTSSession.interrupt()``.
    4. ``speak`` raises ``BargeInInterrupted`` and the demo prints how
       quickly the agent went silent.

This script does NOT spawn the "user" speech itself — it's designed to be
run while you (or a second participant) join the room from the frontend
and talk. If no one talks, the demo just times out gracefully.

Set ``BARGE_IN_SECONDS`` to bound how long we wait before giving up. Set
``BARGE_IN_TEXT`` to override the agent's monologue.

Usage:

    cd backend
    source venv/bin/activate
    python scripts/demo_barge_in.py --room demo-room

Then join the same room from your frontend (or any LiveKit client) and
talk into the mic. You should see the agent cut off mid-sentence within
a few hundred ms of you speaking.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parent.parent
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.livekit.schema import CreateRoomRequest  # noqa: E402
from modules.livekit.service import LiveKitService  # noqa: E402
from modules.stt.deepgram_client import DeepgramSTT  # noqa: E402
from modules.stt.schema import TranscriptEventKind  # noqa: E402
from modules.stt.streamer import STTStreamer  # noqa: E402
from modules.tts.elevenlabs_client import ElevenLabsTTS  # noqa: E402
from modules.tts.streamer import BargeInInterrupted, TTSStreamer  # noqa: E402


DEFAULT_TEXT = (
    "Hello there. I am going to keep talking for a while now so that you "
    "have plenty of time to interrupt me. The whole point of this demo is "
    "to prove that the agent stops speaking as soon as you start. Please "
    "feel free to jump in whenever you are ready."
)


async def main(room: str, text: str, wait_s: float, target: str | None) -> int:
    livekit = LiveKitService()
    tts = ElevenLabsTTS()
    stt = DeepgramSTT()
    tts_streamer = TTSStreamer(
        tts=tts, livekit=livekit, agent_identity="tts-pub", agent_name="TTS"
    )
    stt_streamer = STTStreamer(
        stt=stt, livekit=livekit, agent_identity="stt-sub", agent_name="STT"
    )

    # Try to look the room up first; only create if missing. We never
    # delete a room we didn't create — otherwise we'd boot the browser
    # client that's already joined for the demo and trigger
    # "could not createOffer with closed peer connection" client-side.
    created_room = False
    try:
        await livekit.get_room(room)
        print(f"using existing room: {room}")
    except Exception:
        try:
            await livekit.create_room(
                CreateRoomRequest(name=room, max_participants=8)
            )
            created_room = True
            print(f"created room: {room}")
        except Exception:
            print(f"using existing room: {room}")

        async with tts_streamer.open_session(room=room) as tts_session:
            # Browser mic publishes opus → LiveKit decodes to 48 kHz mono.
            # Filter STT to a specific participant so the agent's own TTS
            # output doesn't trip speech_started and interrupt itself.
            async with stt_streamer.open_session(
                room=room,
                target_participant=target,
                sample_rate=48000,
                num_channels=1,
            ) as stt_session:
                print(
                    "STT subscribed. Join the room from another client and "
                    "start talking to trigger barge-in."
                )

                speak_started = time.monotonic()
                speak_task = asyncio.create_task(
                    tts_session.speak(text, wait_for_playout=False)
                )

                interrupted_at: float | None = None

                async def watcher() -> None:
                    nonlocal interrupted_at
                    async for event in stt_session.events():
                        if event.kind == TranscriptEventKind.SPEECH_STARTED:
                            if not tts_session.is_speaking:
                                continue
                            print(
                                f"  [{event.ts_ms:>5} ms] STT detected "
                                "speech_started — interrupting TTS"
                            )
                            await tts_session.interrupt()
                            interrupted_at = time.monotonic()
                            return
                        if event.kind == TranscriptEventKind.PARTIAL:
                            print(f"  [{event.ts_ms:>5} ms] partial: {event.text!r}")
                        elif event.kind == TranscriptEventKind.FINAL:
                            print(f"  [{event.ts_ms:>5} ms] FINAL:   {event.text!r}")

                watcher_task = asyncio.create_task(watcher())

                try:
                    await asyncio.wait_for(speak_task, timeout=wait_s)
                    print(
                        "  TTS finished naturally — no barge-in event "
                        "was received."
                    )
                except BargeInInterrupted:
                    elapsed_ms = (
                        int((interrupted_at - speak_started) * 1000)
                        if interrupted_at
                        else -1
                    )
                    print(
                        f"  TTS interrupted after {elapsed_ms} ms "
                        "(BargeInInterrupted raised by speak())"
                    )
                except asyncio.TimeoutError:
                    print("  timed out waiting for TTS to finish")
                    speak_task.cancel()

                watcher_task.cancel()
                try:
                    await watcher_task
                except (asyncio.CancelledError, Exception):
                    pass
        return 0
    finally:
        if created_room:
            try:
                await livekit.delete_room(room)
            except Exception as exc:
                print(f"warn: delete_room failed: {exc}")
        await livekit.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--room",
        default=os.environ.get(
            "BARGE_IN_ROOM", f"barge-in-{uuid.uuid4().hex[:6]}"
        ),
    )
    parser.add_argument(
        "--text",
        default=os.environ.get("BARGE_IN_TEXT", DEFAULT_TEXT),
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=float(os.environ.get("BARGE_IN_SECONDS", "60")),
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("BARGE_IN_TARGET"),
        help=(
            "LiveKit participant identity to listen to (e.g. user-<uuid> "
            "from the frontend Calls page). If omitted, STT subscribes to "
            "any remote audio — including the TTS agent itself, which "
            "will cause the demo to interrupt itself immediately."
        ),
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.room, args.text, args.wait, args.target)))
