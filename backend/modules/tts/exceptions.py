"""TTS-specific exceptions translated into HTTP responses by the router."""

from __future__ import annotations


class TTSError(Exception):
    status_code: int = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class TTSConfigError(TTSError):
    status_code = 500


class TTSProviderError(TTSError):
    """Upstream (ElevenLabs) failed or returned an error."""

    status_code = 502


class TTSStreamError(TTSError):
    """Failure while pushing audio into the LiveKit room."""

    status_code = 502
