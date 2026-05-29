#!/usr/bin/env python3
"""Run the live STT → GPT-4o → TTS orchestrator in a LiveKit room.

This is the standalone worker version of :mod:`modules.ai.orchestrator`.
Use it during development to talk to your agent from the browser:

    1. Start the backend infra (docker compose up postgres redis livekit).
    2. Set OPENAI_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY in .env.
    3. python scripts/run_ai_agent.py --room my-test-room
    4. Join `my-test-room` in your frontend (or meet.livekit.io/custom)
       using a fresh token from POST /api/v1/livekit/tokens.
    5. Talk to the agent. Barge-in works: start speaking while the agent
       is mid-utterance and it will stop within ~300ms.

Environment overrides:
  AI_AGENT_PERSONA       (default: outbound_sdr)
  AI_AGENT_FRAMEWORK     (BANT | MEDDICC, default: BANT)
  AI_AGENT_LEAD_NAME, AI_AGENT_COMPANY, AI_AGENT_PRODUCT,
  AI_AGENT_VALUE_PROP, AI_AGENT_OBJECTIVE
  AI_AGENT_OPENING       (defaults to a friendly outbound opener)
  AI_AGENT_IDLE_SECONDS  (hang up after this many seconds of silence)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.logging import configure_logging  # noqa: E402
from modules.ai.dependencies import (  # noqa: E402
    get_ai_service,
    shutdown_ai,
)
from modules.ai.orchestrator import ConversationOrchestrator  # noqa: E402
from modules.livekit.dependencies import (  # noqa: E402
    get_livekit_service,
    shutdown_livekit_service,
)
from modules.livekit.schema import CreateRoomRequest  # noqa: E402
from modules.stt.dependencies import get_stt_streamer  # noqa: E402
from modules.tts.dependencies import get_streamer as get_tts_streamer  # noqa: E402


DEFAULT_OPENING = (
    "Hi there, this is Alex calling from Aifficient. Do you have a quick "
    "minute? I think we can save your SDR team a lot of time."
)


async def amain(args: argparse.Namespace) -> int:
    configure_logging()

    livekit = get_livekit_service()
    ai = get_ai_service()
    stt_streamer = get_stt_streamer()
    tts_streamer = get_tts_streamer()

    # Ensure the room exists. If it already exists LiveKit is idempotent.
    try:
        await livekit.create_room(
            CreateRoomRequest(name=args.room, max_participants=4)
        )
    except Exception as exc:
        print(f"WARN: create_room: {exc} (continuing — room may exist)")

    persona = os.environ.get("AI_AGENT_PERSONA", "outbound_sdr")
    framework = os.environ.get("AI_AGENT_FRAMEWORK", "BANT")
    extra_context = {
        "lead_name": os.environ.get("AI_AGENT_LEAD_NAME", "there"),
        "company": os.environ.get("AI_AGENT_COMPANY", "Aifficient"),
        "product": os.environ.get(
            "AI_AGENT_PRODUCT", "AI outbound calling platform"
        ),
        "value_prop": os.environ.get(
            "AI_AGENT_VALUE_PROP",
            "10x more conversations per SDR per day",
        ),
        "objective": os.environ.get(
            "AI_AGENT_OBJECTIVE", "book a 15-minute discovery call"
        ),
        "agent_name": os.environ.get(
            "AI_AGENT_NAME", "Alex from Aifficient"
        ),
    }
    opening = os.environ.get("AI_AGENT_OPENING", DEFAULT_OPENING)
    idle = float(os.environ.get("AI_AGENT_IDLE_SECONDS", "90"))

    print(f"Joining room: {args.room}")
    print(f"  persona  : {persona}")
    print(f"  framework: {framework}")
    print(f"  target   : {args.target or '(any remote)'}")
    print(f"  opening  : {opening[:80]}{'…' if len(opening) > 80 else ''}")

    orch = ConversationOrchestrator(
        ai=ai,
        stt_streamer=stt_streamer,
        tts_streamer=tts_streamer,
        room=args.room,
        call_id=args.call_id or args.room,
        target_participant=args.target,
        persona=persona,
        framework=framework,
        extra_context=extra_context,
        opening_line=opening,
        idle_timeout_seconds=idle,
    )

    try:
        async with orch.run():
            await orch._stop.wait()  # noqa: SLF001 — internal stop event
    except KeyboardInterrupt:
        pass
    finally:
        try:
            await shutdown_ai()
        except Exception:
            pass
        try:
            await shutdown_livekit_service()
        except Exception:
            pass

    stats = orch.stats
    print("\n=== Conversation stats ===")
    print(f"  turns         : {stats.turns}")
    print(f"  barge-ins     : {stats.barge_ins}")
    print(f"  llm errors    : {stats.llm_errors}")
    print(f"  tts errors    : {stats.tts_errors}")
    print(f"  first reply ms: {stats.first_reply_ms}")
    print(
        f"  qualification : {stats.qualification_status} "
        f"({stats.qualification_score}/100)"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--room",
        default=os.environ.get(
            "AI_AGENT_ROOM", f"ai-agent-{uuid.uuid4().hex[:6]}"
        ),
    )
    parser.add_argument(
        "--call-id",
        default=os.environ.get("AI_AGENT_CALL_ID"),
        help="Defaults to the room name.",
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("AI_AGENT_TARGET"),
        help=(
            "LiveKit participant identity the agent should listen to. "
            "Omit to listen to any remote (will pick up the agent's own "
            "echo unless the room has only one human)."
        ),
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(amain(args)))
