"""Request / response schemas for the TTS API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpeakRequest(BaseModel):
    room: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=5000)
    voice_id: str | None = Field(default=None, max_length=64)
    model_id: str | None = Field(default=None, max_length=64)
    agent_identity: str | None = Field(default=None, max_length=64)
    agent_name: str | None = Field(default=None, max_length=64)
    wait: bool = Field(
        default=True,
        description=(
            "When true (default) the request blocks until streaming has "
            "finished. When false, the speech is dispatched as a background "
            "task and the call returns immediately."
        ),
    )


class SpeakResponse(BaseModel):
    room: str
    voice_id: str
    model_id: str
    bytes_streamed: int
    duration_ms: int
    dispatched: bool = Field(
        default=False,
        description="True when the request was queued as a background task.",
    )


class Voice(BaseModel):
    voice_id: str
    name: str
    category: str | None = None
    description: str | None = None
    preview_url: str | None = None
    labels: dict[str, str] | None = None


class VoiceListResponse(BaseModel):
    voices: list[Voice]
