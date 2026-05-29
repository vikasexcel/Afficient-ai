"""FastAPI dependencies for the STT module."""

from __future__ import annotations

from modules.livekit.dependencies import get_livekit_service
from modules.stt.deepgram_client import DeepgramSTT
from modules.stt.streamer import STTStreamer

_stt: DeepgramSTT | None = None
_streamer: STTStreamer | None = None


def get_stt() -> DeepgramSTT:
    """Process-wide :class:`DeepgramSTT` singleton."""

    global _stt
    if _stt is None:
        _stt = DeepgramSTT()
    return _stt


def get_stt_streamer() -> STTStreamer:
    """Process-wide :class:`STTStreamer` singleton."""

    global _streamer
    if _streamer is None:
        _streamer = STTStreamer(stt=get_stt(), livekit=get_livekit_service())
    return _streamer


def reset_stt_singletons() -> None:
    """Test helper — drops both singletons so the next call rebuilds them."""

    global _stt, _streamer
    _stt = None
    _streamer = None
