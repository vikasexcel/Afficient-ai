"""Request / response schemas for the STT API."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TranscriptEventKind(str, Enum):
    """Normalised stream event types we surface to callers.

    Maps cleanly onto Deepgram's WebSocket message types but is provider
    agnostic so we can swap STT vendors later without changing the
    consumer-facing contract.
    """

    SPEECH_STARTED = "speech_started"
    PARTIAL = "partial"
    FINAL = "final"
    UTTERANCE_END = "utterance_end"


class TranscriptEvent(BaseModel):
    """A single normalised event emitted by an :class:`STTSession`.

    * ``text`` is empty for ``SPEECH_STARTED`` and ``UTTERANCE_END`` events.
    * ``is_final`` is ``True`` for ``FINAL`` events, ``False`` for ``PARTIAL``.
    * ``ts_ms`` is the wall-clock millisecond offset since the session began
      (not Deepgram's audio-time field). Useful for plotting latency.
    """

    kind: TranscriptEventKind
    text: str = ""
    is_final: bool = False
    confidence: float | None = None
    ts_ms: int = 0
    speech_final: bool | None = Field(
        default=None,
        description=(
            "Deepgram's speech_final flag — True when the provider believes "
            "the current utterance has ended (drives turn-taking)."
        ),
    )


class TranscribeRequest(BaseModel):
    """Body for ``POST /api/v1/stt/transcribe``.

    The endpoint joins the given LiveKit room as a subscribe-only agent,
    pumps audio from ``participant_identity`` (or any remote, if omitted)
    into Deepgram for at most ``duration_seconds`` and returns the
    transcript events collected along the way. Intended as a smoke-test /
    debugging tool, not a production transport.
    """

    room: str = Field(min_length=1, max_length=128)
    participant_identity: str | None = Field(default=None, max_length=64)
    duration_seconds: int = Field(default=10, ge=1, le=60)
    interim_results: bool | None = None
    language: str | None = None


class TranscribeResponse(BaseModel):
    room: str
    participant_identity: str | None
    duration_ms: int
    events: list[TranscriptEvent]
