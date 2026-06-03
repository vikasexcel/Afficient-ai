"""HTTP API: ``/api/v1/tts``."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from common.logging import get_logger
from common.security.authorization import requires
from common.security.roles import Role
from config.settings import settings
from modules.tts.dependencies import get_streamer, get_tts
from modules.tts.elevenlabs_client import ElevenLabsTTS
from modules.tts.exceptions import TTSError
from modules.tts.schema import (
    RegistryVoiceOut,
    SpeakRequest,
    SpeakResponse,
    VoiceListResponse,
    VoicePreviewRequest,
    VoiceProviderOut,
    VoiceRegistryResponse,
)
from modules.tts.streamer import TTSStreamer
from modules.tts import voice_registry

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


@router.get("/voice-registry", response_model=VoiceRegistryResponse)
async def voice_registry_endpoint(
    provider: str | None = None,
    gender: str | None = None,
    accent: str | None = None,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    """Curated, human-friendly voices for the playbook Voice Settings UI.

    Voice ids are managed server-side and never hardcoded in the client.
    The list can be extended/overridden via ``TTS_VOICE_REGISTRY_JSON``.
    """

    voices = voice_registry.list_voices(
        provider=provider, gender=gender, accent=accent
    )
    return VoiceRegistryResponse(
        providers=[VoiceProviderOut(**p) for p in voice_registry.provider_catalog()],
        genders=sorted(voice_registry.ALL_GENDERS),
        accents=list(voice_registry.ALL_ACCENTS),
        voices=[RegistryVoiceOut(**v.to_dict()) for v in voices],
    )


@router.post(
    "/voice-preview",
    responses={200: {"content": {"audio/mpeg": {}}}},
)
async def voice_preview(
    data: VoicePreviewRequest,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    tts: ElevenLabsTTS = Depends(get_tts),
):
    """Synthesize a short sample clip for in-browser playback.

    Uses the *exact* voice that will be used on calls (the resolved
    ``voice_id``), falling back to ``ELEVENLABS_VOICE_ID`` when none is
    given. Returns ``audio/mpeg`` bytes the frontend can play directly.
    """

    provider = (data.provider or voice_registry.DEFAULT_VOICE_PROVIDER).lower()
    effective_voice = data.voice_id or tts.default_voice_id
    known = voice_registry.get_voice(provider, effective_voice) if effective_voice else None
    voice_name = known.name if known else (data.voice_id and "Custom") or "default"

    log.info(
        "tts.VOICE_PREVIEW_REQUESTED",
        provider=provider,
        voice_id=effective_voice,
        voice_name=voice_name,
        chars=len(data.text),
    )

    if not voice_registry.is_enabled_provider(provider):
        log.warning(
            "tts.VOICE_PREVIEW_FAILED",
            provider=provider,
            voice_id=effective_voice,
            reason="provider_not_enabled",
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Voice provider '{provider}' is not available yet. "
                "Use ElevenLabs for now."
            ),
        )

    try:
        audio = await tts.synthesize(
            data.text,
            voice_id=data.voice_id or None,
            model_id=data.model_id,
            output_format=settings.ELEVENLABS_PREVIEW_FORMAT,
        )
    except TTSError as exc:
        log.warning(
            "tts.VOICE_PREVIEW_FAILED",
            provider=provider,
            voice_id=effective_voice,
            voice_name=voice_name,
            error=exc.message,
        )
        raise _to_http(exc) from exc

    log.info(
        "tts.VOICE_PREVIEW_SUCCESS",
        provider=provider,
        voice_id=effective_voice,
        voice_name=voice_name,
        bytes=len(audio),
    )
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


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
