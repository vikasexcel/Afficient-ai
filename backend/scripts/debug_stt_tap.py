#!/usr/bin/env python3
"""Diagnostic: capture LiveKit frames AND send them to Deepgram in parallel.

For each frame received from LiveKit:
  1. write to /tmp/tap.wav
  2. send identical bytes to a live Deepgram session

If the WAV plays back fine but Deepgram returns empty transcripts, the
issue is in our send loop (frame ordering, threading, etc). If both
fail, the LiveKit→bytes conversion is wrong.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parent.parent
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.livekit.schema import TokenRequest  # noqa: E402
from modules.livekit.service import LiveKitService  # noqa: E402
from modules.livekit.transport import AudioTransport  # noqa: E402
from modules.stt.deepgram_client import DeepgramSTT  # noqa: E402


async def main(room: str, target: str, seconds: float, out: str) -> int:
    livekit = LiveKitService()
    stt = DeepgramSTT()

    token = livekit.generate_token(
        TokenRequest(
            room=room, identity="debug-tap", name="tap",
            can_publish=False, can_subscribe=True, can_publish_data=False,
        )
    )
    transport = AudioTransport(token=token.token, url=token.url)
    await transport.connect(auto_publish=False)

    async with stt.open_session(sample_rate=48000, num_channels=1) as session:
        chunks: list[bytes] = []
        sent_bytes = 0
        sent_frames = 0
        first_rate = None

        async def pump() -> None:
            nonlocal sent_bytes, sent_frames, first_rate
            async for frame in transport.iter_audio(participant_identity=target):
                if first_rate is None:
                    first_rate = frame.sample_rate
                    print(f"  first frame: rate={frame.sample_rate} ch={frame.num_channels} bytes={len(frame.data)}")
                chunks.append(frame.data)
                await session.send_audio(frame.data)
                sent_bytes += len(frame.data)
                sent_frames += 1

        async def listen() -> None:
            async for ev in session.events():
                print(f"  EV {ev.kind.value:14} final={ev.is_final} text={ev.text!r}")

        pump_task = asyncio.create_task(pump())
        listen_task = asyncio.create_task(listen())
        try:
            await asyncio.wait_for(asyncio.shield(pump_task), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        pump_task.cancel()
        try: await pump_task
        except: pass
        await asyncio.sleep(2)
        listen_task.cancel()
        try: await listen_task
        except: pass

        with wave.open(out, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(first_rate or 48000)
            wf.writeframes(b"".join(chunks))
        print(f"\nframes sent to deepgram: {sent_frames}")
        print(f"bytes  sent to deepgram: {sent_bytes}")
        print(f"WAV tap written to:      {out}")

    await transport.disconnect()
    await livekit.aclose()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--room", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--seconds", type=float, default=10)
    p.add_argument("--out", default="/tmp/tap.wav")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.room, a.target, a.seconds, a.out)))
