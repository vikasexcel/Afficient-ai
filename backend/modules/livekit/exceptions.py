"""LiveKit module exceptions.

These are translated into HTTP responses by the router layer so callers see
stable, well-typed errors instead of raw SDK exceptions.
"""

from __future__ import annotations


class LiveKitError(Exception):
    """Base error for LiveKit operations."""

    status_code: int = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class LiveKitConfigError(LiveKitError):
    status_code = 500


class RoomNotFoundError(LiveKitError):
    status_code = 404


class RoomAlreadyExistsError(LiveKitError):
    status_code = 409


class TokenGenerationError(LiveKitError):
    status_code = 500


class TransportError(LiveKitError):
    status_code = 502
