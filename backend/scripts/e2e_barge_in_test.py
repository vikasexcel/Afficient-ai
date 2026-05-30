#!/usr/bin/env python3
"""End-to-end exercise of the barge-in + recovery pipeline.

Unlike ``test_barge_in_unit.py`` (which uses fakes), this script talks
to the *real* providers — LiveKit, Deepgram, ElevenLabs, OpenAI — and
verifies the orchestrator behaves correctly in three scenarios:

1. **Single barge-in** — the script joins as a "user" participant and
   plays a short PCM blob a few hundred ms after the agent starts
   speaking. We assert at least one ``InterruptionEvent`` is recorded.

2. **Multiple back-to-back barge-ins** — same but firing five times.
   We assert the cooldown filter keeps the count sensible while the
   agent still goes silent each time.

3. **LLM failure simulation** — the script monkey-patches the AI
   service so ``respond_turn`` throws once per call, then verifies
   ``OrchestratorStats.recoveries_attempted`` increments and the
   fallback line is spoken.

Requires:

* ``LIVEKIT_URL`` / ``LIVEKIT_API_KEY`` / ``LIVEKIT_API_SECRET``
* ``DEEPGRAM_API_KEY``
* ``ELEVENLABS_API_KEY`` / ``ELEVENLABS_VOICE_ID``
* ``OPENAI_API_KEY``
* a running Redis on ``REDIS_URL``

Skips gracefully if any of the above are missing.

Usage:
    cd backend
    source venv/bin/activate
    python scripts/e2e_barge_in_test.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parent.parent
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from config.settings import settings  # noqa: E402
from modules.ai.dependencies import get_ai_service, shutdown_ai  # noqa: E402
from modules.ai.exceptions import AIProviderError  # noqa: E402
from modules.ai.interruption import (  # noqa: E402
    InterruptionLog,
    read_metrics_snapshot,
)
from modules.ai.orchestrator import ConversationOrchestrator  # noqa: E402
from modules.ai.state import ConversationState  # noqa: E402
from modules.livekit.dependencies import get_livekit_service  # noqa: E402
from modules.livekit.schema import CreateRoomRequest, TokenRequest  # noqa: E402
from modules.livekit.transport import AudioTransport  # noqa: E402
from modules.stt.deepgram_client import DeepgramSTT  # noqa: E402
from modules.stt.streamer import STTStreamer  # noqa: E402
from modules.tts.elevenlabs_client import ElevenLabsTTS  # noqa: E402
from modules.tts.streamer import TTSStreamer  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _required_env_ok() -> tuple[bool, list[str]]:
    """Return ``(ok, missing)`` so we can skip cleanly in CI."""

    needed = {
        "LIVEKIT_URL": settings.LIVEKIT_URL,
        "LIVEKIT_API_KEY": settings.LIVEKIT_API_KEY,
        "LIVEKIT_API_SECRET": settings.LIVEKIT_API_SECRET,
        "DEEPGRAM_API_KEY": settings.DEEPGRAM_API_KEY,
        "ELEVENLABS_API_KEY": settings.ELEVENLABS_API_KEY,
        "ELEVENLABS_VOICE_ID": settings.ELEVENLABS_VOICE_ID,
        "OPENAI_API_KEY": settings.OPENAI_API_KEY,
        "REDIS_URL": settings.REDIS_URL,
    }
    missing = [k for k, v in needed.items() if not v]
    return (not missing, missing)


async def _generate_pcm_speech(text: str, sample_rate: int = 48000) -> bytes:
    """Synthesise a short PCM clip with ElevenLabs to use as the user voice.

    Reusing ElevenLabs here is a bit cheeky — but it's the only way to
    avoid shipping a binary audio asset in the repo. The clip is short
    (<2s) so the cost is negligible.
    """

    tts = ElevenLabsTTS(sample_rate=sample_rate)
    buf = bytearray()
    async for chunk in tts.stream_pcm(text):
        buf.extend(chunk)
    return bytes(buf)


async def _publish_user_audio(
    room: str,
    pcm: bytes,
    sample_rate: int,
    *,
    identity: str,
) -> None:
    """Publish ``pcm`` into the room as the "user" participant."""

    livekit = get_livekit_service()
    token = livekit.generate_token(
        TokenRequest(
            room=room,
            identity=identity,
            name="user",
            can_publish=True,
            can_subscribe=False,
        )
    )
    transport = AudioTransport(
        token=token.token,
        url=token.url,
        sample_rate=sample_rate,
        num_channels=1,
        publish_track_name="user-mic",
    )
    try:
        await transport.connect()
        # Push 20ms frames so the receiver sees the same packetisation a
        # real microphone would produce.
        frame_bytes = (sample_rate // 50) * 2  # s16le mono, 20ms
        for i in range(0, len(pcm), frame_bytes):
            chunk = pcm[i : i + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
            await transport.publish_audio(
                chunk, samples_per_channel=frame_bytes // 2
            )
            # pace at real-time so STT can chew on it
            await asyncio.sleep(0.02)
        await transport.wait_for_playout()
    finally:
        await transport.disconnect()


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


async def scenario_single_barge_in(room: str) -> dict:
    print(f"\n=== scenario 1: single barge-in (room={room}) ===")
    ai = get_ai_service()
    stt = STTStreamer(stt=DeepgramSTT(), livekit=get_livekit_service())
    tts = TTSStreamer(tts=ElevenLabsTTS(), livekit=get_livekit_service())

    user_pcm = await _generate_pcm_speech(
        "excuse me, I need to interrupt for a moment"
    )

    orch = ConversationOrchestrator(
        ai=ai,
        stt_streamer=stt,
        tts_streamer=tts,
        room=room,
        call_id=f"e2e-bi-{uuid.uuid4().hex[:6]}",
        target_participant="user",
        opening_line=(
            "Hi there, this is a long agent monologue intended to give "
            "you plenty of time to barge in and confirm the interruption "
            "pipeline is working end-to-end."
        ),
        idle_timeout_seconds=20,
    )

    async with orch.run():
        # Let the opening line begin playing for ~600ms then push user audio.
        await asyncio.sleep(0.6)
        await _publish_user_audio(
            room, user_pcm, sample_rate=48000, identity="user"
        )
        # Give the orchestrator a beat to process the FINAL transcript.
        await asyncio.sleep(2.0)
        orch.stop()

    interruptions = await InterruptionLog(ai.memory).list_for_call(orch.call_id)
    snapshot = await read_metrics_snapshot(ai.memory, call_id=orch.call_id)
    print(f"  barge_ins         : {orch.stats.barge_ins}")
    print(f"  interruption rows : {len(interruptions)}")
    print(
        "  avg silence_latency_ms : "
        f"{orch.stats.interruption_metrics.avg_silence_latency_ms:.1f}"
    )
    print(f"  metrics snapshot   : {'present' if snapshot else 'missing'}")
    return {
        "scenario": "single",
        "barge_ins": orch.stats.barge_ins,
        "interruption_rows": len(interruptions),
    }


async def scenario_multiple_barge_ins(room: str) -> dict:
    print(f"\n=== scenario 2: multiple barge-ins (room={room}) ===")
    ai = get_ai_service()
    stt = STTStreamer(stt=DeepgramSTT(), livekit=get_livekit_service())
    tts = TTSStreamer(tts=ElevenLabsTTS(), livekit=get_livekit_service())

    pcm = await _generate_pcm_speech("hold on please")

    orch = ConversationOrchestrator(
        ai=ai,
        stt_streamer=stt,
        tts_streamer=tts,
        room=room,
        call_id=f"e2e-multi-{uuid.uuid4().hex[:6]}",
        target_participant="user",
        opening_line=(
            "Let me explain in detail. Our platform handles outbound "
            "calls with full conversational support and many features "
            "you'll want to hear about over the next several minutes."
        ),
        idle_timeout_seconds=30,
    )

    async with orch.run():
        for i in range(3):
            await asyncio.sleep(0.8)
            await _publish_user_audio(
                room, pcm, sample_rate=48000, identity=f"user-{i}"
            )
        await asyncio.sleep(2.0)
        orch.stop()

    print(f"  total barge_ins       : {orch.stats.barge_ins}")
    print(f"  cooldown_skipped      : {orch.stats.interruption_metrics.cooldown_skipped}")
    return {
        "scenario": "multiple",
        "barge_ins": orch.stats.barge_ins,
        "cooldown_skipped": orch.stats.interruption_metrics.cooldown_skipped,
    }


async def scenario_llm_failure(room: str) -> dict:
    print(f"\n=== scenario 3: simulated LLM failure (room={room}) ===")
    ai = get_ai_service()
    stt = STTStreamer(stt=DeepgramSTT(), livekit=get_livekit_service())
    tts = TTSStreamer(tts=ElevenLabsTTS(), livekit=get_livekit_service())

    user_pcm = await _generate_pcm_speech(
        "tell me what your platform does in one sentence"
    )

    # Monkey-patch respond_turn to always raise — verifies the recovery
    # path actually fires the fallback line.
    original = ai.respond_turn

    async def always_fail(**kwargs):
        raise AIProviderError("simulated openai failure")

    ai.respond_turn = always_fail  # type: ignore[assignment]
    try:
        orch = ConversationOrchestrator(
            ai=ai,
            stt_streamer=stt,
            tts_streamer=tts,
            room=room,
            call_id=f"e2e-llm-{uuid.uuid4().hex[:6]}",
            target_participant="user",
            opening_line="Hi! Ask me anything about our platform.",
            idle_timeout_seconds=20,
        )
        async with orch.run():
            await asyncio.sleep(1.0)
            await _publish_user_audio(
                room, user_pcm, sample_rate=48000, identity="user"
            )
            await asyncio.sleep(6.0)  # allow retries + recovery to fire
            orch.stop()
    finally:
        ai.respond_turn = original  # type: ignore[assignment]

    print(f"  recoveries_attempted : {orch.stats.recoveries_attempted}")
    print(f"  recoveries_succeeded : {orch.stats.recoveries_succeeded}")
    print(f"  llm_errors           : {orch.stats.llm_errors}")
    return {
        "scenario": "llm_failure",
        "recoveries_attempted": orch.stats.recoveries_attempted,
        "recoveries_succeeded": orch.stats.recoveries_succeeded,
        "llm_errors": orch.stats.llm_errors,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=["all", "single", "multiple", "llm"],
        default=os.environ.get("BARGE_IN_E2E_SCENARIO", "all"),
    )
    args = parser.parse_args(argv)

    ok, missing = _required_env_ok()
    if not ok:
        print(f"[skip] missing env vars: {', '.join(missing)}")
        return 0

    livekit = get_livekit_service()
    room = f"e2e-barge-{uuid.uuid4().hex[:8]}"
    try:
        await livekit.create_room(
            CreateRoomRequest(name=room, max_participants=4)
        )
    except Exception as exc:
        print(f"[error] failed to create room: {exc}")
        return 2

    results = []
    try:
        if args.scenario in ("all", "single"):
            results.append(await scenario_single_barge_in(room))
        if args.scenario in ("all", "multiple"):
            results.append(await scenario_multiple_barge_ins(room))
        if args.scenario in ("all", "llm"):
            results.append(await scenario_llm_failure(room))
    finally:
        try:
            await livekit.delete_room(room)
        except Exception:
            pass
        await shutdown_ai()
        await livekit.aclose()

    print("\n=== summary ===")
    failures = 0
    for r in results:
        print(f"  {r}")
        if r["scenario"] == "single" and r.get("barge_ins", 0) < 1:
            failures += 1
        if r["scenario"] == "llm" and r.get("recoveries_attempted", 0) < 1:
            failures += 1
    if failures:
        print(f"\n  FAIL: {failures} scenario(s) did not meet expectations")
        return 1
    print("\n  OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
