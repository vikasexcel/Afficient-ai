"""Async ElevenLabs TTS client.

Yields raw PCM 16-bit mono chunks suitable for piping into LiveKit's
``rtc.AudioSource``. The output sample rate is configurable; we default to
24 kHz which matches ElevenLabs' lowest-latency PCM profile that LiveKit
can carry without resampling.
"""

from __future__ import annotations

from typing import AsyncIterator

from elevenlabs.client import AsyncElevenLabs

from common.logging import get_logger
from config.settings import settings
from modules.tts.exceptions import TTSConfigError, TTSProviderError
from modules.tts.schema import Voice

log = get_logger("tts.elevenlabs")


_SUPPORTED_SAMPLE_RATES = {8000, 16000, 22050, 24000, 44100, 48000}


class ElevenLabsTTS:
    """Thin async wrapper around the ElevenLabs Python SDK."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_voice_id: str | None = None,
        default_model_id: str | None = None,
        sample_rate: int | None = None,
    ) -> None:
        api_key = api_key or settings.ELEVENLABS_API_KEY
        if not api_key:
            raise TTSConfigError("ELEVENLABS_API_KEY is not set")

        rate = sample_rate or settings.ELEVENLABS_SAMPLE_RATE
        if rate not in _SUPPORTED_SAMPLE_RATES:
            raise TTSConfigError(
                f"unsupported sample rate {rate}; expected one of "
                f"{sorted(_SUPPORTED_SAMPLE_RATES)}"
            )

        self._client = AsyncElevenLabs(api_key=api_key)
        self._default_voice_id = default_voice_id or settings.ELEVENLABS_VOICE_ID
        self._default_model_id = (
            default_model_id or settings.ELEVENLABS_MODEL_ID or "eleven_turbo_v2_5"
        )
        self._sample_rate = rate
        self._output_format = f"pcm_{rate}"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def default_voice_id(self) -> str:
        return self._default_voice_id

    @property
    def default_model_id(self) -> str:
        return self._default_model_id

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def stream_pcm(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        model_id: str | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield raw PCM16 mono chunks at ``self.sample_rate`` Hz."""

        voice = voice_id or self._default_voice_id
        if not voice:
            raise TTSConfigError(
                "voice_id is required (set ELEVENLABS_VOICE_ID or pass voice_id)"
            )
        model = model_id or self._default_model_id

        log.info(
            "tts.stream.start",
            voice_id=voice,
            model_id=model,
            chars=len(text),
            sample_rate=self._sample_rate,
        )

        try:
            stream = self._client.text_to_speech.convert(
                voice_id=voice,
                text=text,
                model_id=model,
                output_format=self._output_format,
                optimize_streaming_latency=3,
            )
            async for chunk in stream:
                if chunk:
                    yield chunk
        except Exception as exc:
            log.exception("tts.stream.failed", voice_id=voice)
            raise TTSProviderError(f"ElevenLabs stream failed: {exc}") from exc

        log.info("tts.stream.end", voice_id=voice)

    # ------------------------------------------------------------------
    # Voices
    # ------------------------------------------------------------------

    async def list_voices(self) -> list[Voice]:
        try:
            resp = await self._client.voices.get_all()
        except Exception as exc:
            log.exception("tts.voices.failed")
            raise TTSProviderError(f"failed to list voices: {exc}") from exc

        out: list[Voice] = []
        for v in resp.voices:
            out.append(
                Voice(
                    voice_id=v.voice_id,
                    name=v.name or v.voice_id,
                    category=getattr(v, "category", None),
                    description=getattr(v, "description", None),
                    preview_url=getattr(v, "preview_url", None),
                    labels=getattr(v, "labels", None) or None,
                )
            )
        return out
