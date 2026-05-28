"""FastAPI dependencies for the LiveKit module.

We keep a single :class:`LiveKitService` per process. The instance is
constructed lazily on first request, then reused. It must be explicitly
closed on application shutdown via :func:`shutdown_livekit_service`.
"""

from __future__ import annotations

from modules.livekit.service import LiveKitService

_service: LiveKitService | None = None


def get_livekit_service() -> LiveKitService:
    """FastAPI dependency that returns the shared :class:`LiveKitService`."""

    global _service
    if _service is None:
        _service = LiveKitService()
    return _service


async def shutdown_livekit_service() -> None:
    global _service
    if _service is not None:
        await _service.aclose()
        _service = None
