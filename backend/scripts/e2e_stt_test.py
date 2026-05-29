#!/usr/bin/env python3
"""End-to-end STT smoke test.

Flow:
    1. Open a LiveKit room.
    2. Start an STT agent subscribed to the room (Deepgram live socket).
    3. Use the TTS streamer to publish a known sentence into the room as
       a separate agent participant.
    4. Wait until Deepgram emits at least one final transcript or the
       overall timeout elapses.
    5. Assert the transcript contains a sentinel word from the sentence.

This exercises the full ingest path (LiveKit subscribe → PCM frames →
Deepgram WebSocket → normalised TranscriptEvents) end-to-end against
real services. Requires ELEVENLABS_API_KEY, DEEPGRAM_API_KEY, and a
reachable LiveKit server (the dev compose stack is fine).

Usage:

    cd backend
    source venv/bin/activate
    python scripts/e2e_stt_test.py
"""

from __future__ import annotations

import asyncio
import sys
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
from modules.tts.streamer import TTSStreamer  # noqa: E402


# Sentence picked because every word is unambiguous to Deepgram and the
# sentinel ("aifficient") is unusual enough that we can assert on it
# (smart formatting tends to leave proper nouns alone).
SENTENCE = "Hello, this is a quick transcription test for Aifficient."
SENTINELS = ("aifficient", "transcription", "test")
TIMEOUT_SECONDS = 25


async def _wait_for_final(session, deadline_s: float) -> str:
    """Block until Deepgram emits any final transcript or ``deadline_s``."""

    text = ""
    try:
        async def collect() -> None:
            nonlocal text
            async for event in session.events():
                if event.kind == TranscriptEventKind.FINAL and event.text:
                    text = event.text
                    return

        await asyncio.wait_for(collect(), timeout=deadline_s)
    except asyncio.TimeoutError:
        pass
    return text


async def main() -> int:
    livekit = LiveKitService()
    tts = ElevenLabsTTS()
    stt = DeepgramSTT()
    tts_streamer = TTSStreamer(
        tts=tts, livekit=livekit, agent_identity="tts-pub", agent_name="TTS"
    )
    stt_streamer = STTStreamer(
        stt=stt, livekit=livekit, agent_identity="stt-sub", agent_name="STT"
    )

    room_name = f"stt-e2e-{uuid.uuid4().hex[:8]}"
    print(f"creating room: {room_name}")
    await livekit.create_room(CreateRoomRequest(name=room_name, max_participants=4))

    try:
        # Match the TTS publisher's sample rate so LiveKit doesn't need to
        # resample on the subscribe side. ElevenLabs streams at 24 kHz.
        sample_rate = tts.sample_rate

        async with stt_streamer.open_session(
            room=room_name,
            target_participant="tts-pub",
            sample_rate=sample_rate,
            num_channels=1,
        ) as stt_session:
            print("stt agent connected; speaking sentence...")
            speak_task = asyncio.create_task(
                tts_streamer.speak_into_room(room=room_name, text=SENTENCE)
            )

            transcript = await _wait_for_final(stt_session, TIMEOUT_SECONDS)
            try:
                await asyncio.wait_for(speak_task, timeout=10)
            except asyncio.TimeoutError:
                speak_task.cancel()

            stats = stt_session.stats

        print("\n=== STT stats ===")
        print(f"events:           {stats.events_emitted}")
        print(f"  partials:       {stats.partials}")
        print(f"  finals:         {stats.finals}")
        print(f"  speech_started: {stats.speech_started_events}")
        print(f"  utterance_end:  {stats.utterance_end_events}")
        print(f"first event @:    {stats.first_event_ms} ms")
        print(f"frames pushed:    {stats.frames_pushed}")
        print(f"bytes pushed:     {stats.bytes_pushed}")
        print(f"final transcript: {transcript!r}")

        lowered = transcript.lower()
        if not transcript:
            print("\nFAIL: no final transcript received within timeout")
            return 1
        if not any(s in lowered for s in SENTINELS):
            print(
                "\nFAIL: transcript does not contain any sentinel word "
                f"({SENTINELS})"
            )
            return 1
        print("\nOK: transcript contained a sentinel word")
        return 0
    finally:
        try:
            await livekit.delete_room(room_name)
        except Exception as exc:
            print(f"warn: delete_room failed: {exc}")
        await livekit.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
