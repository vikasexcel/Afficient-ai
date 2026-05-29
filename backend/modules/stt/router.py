"""HTTP API for the STT module.

Currently exposes a single smoke-test endpoint that bounded-transcribes a
room for N seconds and returns the events. Production conversational use
should drive :class:`STTStreamer` directly from the agent process — HTTP
request/response is the wrong shape for a live conversation loop.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException

from common.logging import get_logger
from common.security.authorization import requires
from common.security.roles import Role
from modules.stt.dependencies import get_stt_streamer
from modules.stt.exceptions import STTError
from modules.stt.schema import (
    TranscribeRequest,
    TranscribeResponse,
)
from modules.stt.streamer import STTStreamer

log = get_logger("stt.router")

router = APIRouter(prefix="/stt", tags=["stt"])


def _to_http(exc: STTError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    data: TranscribeRequest,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    streamer: STTStreamer = Depends(get_stt_streamer),
):
    """Subscribe to ``room`` for ``duration_seconds`` and return events.

    Intended for debugging / smoke-testing the STT pipeline against a
    running room. Not suitable for production conversation flows — those
    should hold the session open and react to events in real time.
    """

    started = time.monotonic()
    try:
        stats = await streamer.transcribe_for(
            room=data.room,
            duration_seconds=data.duration_seconds,
            target_participant=data.participant_identity,
            language=data.language,
            interim_results=data.interim_results,
        )
    except STTError as exc:
        raise _to_http(exc) from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "stt.transcribe.done",
        room=data.room,
        target=data.participant_identity,
        events=len(stats.events),
        finals=stats.finals,
        partials=stats.partials,
        duration_ms=duration_ms,
    )
    return TranscribeResponse(
        room=data.room,
        participant_identity=data.participant_identity,
        duration_ms=duration_ms,
        events=stats.events,
    )
