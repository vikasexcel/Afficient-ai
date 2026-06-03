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
    stages: dict[str, int] | None = Field(
        default=None,
        description=(
            "Per-stage timing breakdown in milliseconds (token_mint_ms, "
            "connect_ms, ttfb_ms, first_frame_pub_ms, stream_end_ms, "
            "playout_wait_ms, disconnect_ms, total_ms). Present only on "
            "synchronous (wait=true) requests."
        ),
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


# ---------------------------------------------------------------------------
# Voice registry + preview
# ---------------------------------------------------------------------------


class RegistryVoiceOut(BaseModel):
    """A curated, human-friendly voice for the playbook UI dropdowns."""

    provider: str
    voice_id: str
    name: str
    gender: str
    accent: str
    language: str = "en"
    description: str | None = None


class VoiceProviderOut(BaseModel):
    id: str
    label: str
    enabled: bool


class VoiceRegistryResponse(BaseModel):
    providers: list[VoiceProviderOut]
    genders: list[str]
    accents: list[str]
    voices: list[RegistryVoiceOut]


class VoicePreviewRequest(BaseModel):
    """Render a short sample clip for the exact voice used on calls."""

    voice_id: str | None = Field(default=None, max_length=64)
    provider: str | None = Field(default=None, max_length=32)
    model_id: str | None = Field(default=None, max_length=64)
    text: str = Field(
        default="Hi, this is your AI agent. Thank you for taking my call.",
        min_length=1,
        max_length=600,
    )
