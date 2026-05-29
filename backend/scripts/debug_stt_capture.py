#!/usr/bin/env python3
"""Diagnostic: capture N seconds of a participant's audio to a WAV file.

Subscribes to the given LiveKit room as a passive agent and writes every
PCM frame from ``--target`` to ``--out``. Lets you listen to exactly what
Deepgram (or any STT) would receive — if the WAV is silence, the problem
is upstream (mic muted, browser permissions, wrong track). If the WAV
sounds clear but STT returns empty transcripts, the problem is in the
STT pipeline (sample rate, encoding, model).

Usage:

    cd backend
    source venv/bin/activate
    python scripts/debug_stt_capture.py \
        --room call-XXXX \
        --target user-<uuid> \
        --seconds 8 \
        --out /tmp/mic.wav
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
import wave
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parent.parent
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from modules.livekit.schema import TokenRequest  # noqa: E402
from modules.livekit.service import LiveKitService  # noqa: E402
from modules.livekit.transport import AudioTransport  # noqa: E402


async def main(room: str, target: str | None, seconds: float, out: str) -> int:
    livekit = LiveKitService()
    token = livekit.generate_token(
        TokenRequest(
            room=room,
            identity="debug-stt-capture",
            name="Debug Capture",
            can_publish=False,
            can_subscribe=True,
            can_publish_data=False,
        )
    )
    transport = AudioTransport(token=token.token, url=token.url)
    await transport.connect(auto_publish=False)

    sample_rate = 48000
    channels = 1
    frames: list[bytes] = []
    n_frames = 0
    rms_sum = 0
    max_abs = 0
    actual_rate = None
    actual_channels = None

    async def collect() -> None:
        nonlocal n_frames, rms_sum, max_abs, actual_rate, actual_channels
        async for frame in transport.iter_audio(participant_identity=target):
            if actual_rate is None:
                actual_rate = frame.sample_rate
                actual_channels = frame.num_channels
                print(
                    f"  first frame: sample_rate={frame.sample_rate} "
                    f"channels={frame.num_channels} "
                    f"samples={frame.samples_per_channel} "
                    f"bytes={len(frame.data)}"
                )
            frames.append(frame.data)
            n_frames += 1
            # Cheap RMS approximation over int16 samples
            n_samples = len(frame.data) // 2
            if n_samples:
                vals = struct.unpack(f"<{n_samples}h", frame.data)
                for v in vals:
                    rms_sum += v * v
                    if abs(v) > max_abs:
                        max_abs = abs(v)

    try:
        await asyncio.wait_for(collect(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        await transport.disconnect()
        await livekit.aclose()

    if not frames:
        print("FAIL: no frames received")
        return 1

    rate = actual_rate or sample_rate
    ch = actual_channels or channels
    pcm = b"".join(frames)
    with wave.open(out, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)

    n_samples = len(pcm) // 2
    rms = int((rms_sum / max(n_samples, 1)) ** 0.5)
    duration_s = n_samples / rate / ch
    print(f"frames:        {n_frames}")
    print(f"bytes:         {len(pcm)}")
    print(f"duration:      {duration_s:.2f} s")
    print(f"sample rate:   {rate} Hz")
    print(f"channels:      {ch}")
    print(f"max |sample|:  {max_abs} / 32767  ({100*max_abs/32767:.1f}% full scale)")
    print(f"approx RMS:    {rms} ({100*rms/32767:.2f}% full scale)")
    print(f"wrote:         {out}")
    print()
    if max_abs < 200:
        print("VERDICT: audio is effectively silent — mic muted, no input, "
              "or browser permissions denied")
    elif rms < 200:
        print("VERDICT: very low gain — check OS / browser input level")
    else:
        print("VERDICT: audio looks present. Open the WAV to listen.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", required=True)
    parser.add_argument("--target", default=None)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--out", default="/tmp/mic.wav")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.room, args.target, args.seconds, args.out)))
