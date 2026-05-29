"""Exception hierarchy for the STT module.

Mirrors the shape used by :mod:`modules.tts` so HTTP handlers can do
``isinstance(exc, STTError)`` and translate to ``HTTPException`` uniformly.
"""

from __future__ import annotations


class STTError(Exception):
    """Base class for any STT-related failure."""

    status_code: int = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class STTConfigError(STTError):
    """Misconfiguration (missing API key, unsupported sample rate, ...)."""

    status_code = 500


class STTProviderError(STTError):
    """Upstream provider (Deepgram) returned an error or dropped the socket."""

    status_code = 502


class STTStreamError(STTError):
    """Failure while bridging LiveKit audio into the STT provider."""

    status_code = 502
