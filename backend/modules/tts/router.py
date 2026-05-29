"""HTTP API: ``/api/v1/tts``."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from common.logging import get_logger
from common.security.authorization import requires
from common.security.roles import Role
from modules.tts.dependencies import get_streamer, get_tts
from modules.tts.elevenlabs_client import ElevenLabsTTS
from modules.tts.exceptions import TTSError
from modules.tts.schema import (
    SpeakRequest,
    SpeakResponse,
    VoiceListResponse,
)
from modules.tts.streamer import TTSStreamer

log = get_logger("tts.router")

router = APIRouter(prefix="/tts", tags=["tts"])


def _to_http(exc: TTSError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/voices", response_model=VoiceListResponse)
async def list_voices(
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    tts: ElevenLabsTTS = Depends(get_tts),
):
    try:
        voices = await tts.list_voices()
    except TTSError as exc:
        raise _to_http(exc) from exc
    return VoiceListResponse(voices=voices)


@router.post("/speak", response_model=SpeakResponse)
async def speak(
    data: SpeakRequest,
    background_tasks: BackgroundTasks,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    streamer: TTSStreamer = Depends(get_streamer),
):
    """Speak ``text`` into ``room`` using ElevenLabs.

    With ``wait=true`` (default) the response includes bytes streamed and
    elapsed time. With ``wait=false`` the streaming is dispatched as a
    background task and the response returns immediately.
    """

    voice_id = data.voice_id or streamer._tts.default_voice_id  # noqa: SLF001
    model_id = data.model_id or streamer._tts.default_model_id  # noqa: SLF001

    if not data.wait:
        background_tasks.add_task(
            _speak_safe,
            streamer,
            data,
        )
        log.info(
            "tts.dispatch",
            room=data.room,
            voice_id=voice_id,
            chars=len(data.text),
        )
        return SpeakResponse(
            room=data.room,
            voice_id=voice_id,
            model_id=model_id,
            bytes_streamed=0,
            duration_ms=0,
            dispatched=True,
        )

    try:
        stats = await streamer.speak_into_room(
            room=data.room,
            text=data.text,
            voice_id=data.voice_id,
            model_id=data.model_id,
            agent_identity=data.agent_identity,
            agent_name=data.agent_name,
        )
    except TTSError as exc:
        raise _to_http(exc) from exc

    return SpeakResponse(
        room=data.room,
        voice_id=voice_id,
        model_id=model_id,
        bytes_streamed=stats.bytes_streamed,
        duration_ms=stats.total_ms,
        stages=stats.timings(),
    )


async def _speak_safe(streamer: TTSStreamer, data: SpeakRequest) -> None:
    try:
        await streamer.speak_into_room(
            room=data.room,
            text=data.text,
            voice_id=data.voice_id,
            model_id=data.model_id,
            agent_identity=data.agent_identity,
            agent_name=data.agent_name,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("tts.background.failed", room=data.room)
