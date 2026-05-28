"""FastAPI dependencies for the TTS module."""

from __future__ import annotations

from modules.livekit.dependencies import get_livekit_service
from modules.tts.elevenlabs_client import ElevenLabsTTS
from modules.tts.streamer import TTSStreamer

_tts: ElevenLabsTTS | None = None
_streamer: TTSStreamer | None = None


def get_tts() -> ElevenLabsTTS:
    """Process-wide :class:`ElevenLabsTTS` singleton."""

    global _tts
    if _tts is None:
        _tts = ElevenLabsTTS()
    return _tts


def get_streamer() -> TTSStreamer:
    """Process-wide :class:`TTSStreamer` singleton."""

    global _streamer
    if _streamer is None:
        _streamer = TTSStreamer(tts=get_tts(), livekit=get_livekit_service())
    return _streamer


def reset_tts_singletons() -> None:
    """Test helper — drops both singletons so the next call rebuilds them."""

    global _tts, _streamer
    _tts = None
    _streamer = None
