"""Lightweight in-process fakes for external integrations.

Used by the unit / API / latency suites to exercise code paths that talk
to OpenAI / Deepgram / ElevenLabs / Twilio / LiveKit without touching
the real providers.

Design rules:

* Fakes mirror the *public* surface used by the production code (i.e.
  the methods the orchestrator/router actually call).
* They are *deterministic*: a given input always produces the same
  output so latency benchmarks have low variance.
* They report stats compatible with ``ChatTurnStats`` /
  ``InterruptResult`` etc. so callers don't need fake-aware branches.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Iterable

from modules.ai.openai_client import StreamChunk
from modules.ai.schema import ChatMessage, ChatTurnResult, ChatTurnStats, MessageRole
from modules.livekit.schema import (
    CreateRoomRequest,
    RoomResponse,
    TokenRequest,
    TokenResponse,
)
from modules.stt.schema import TranscriptEvent, TranscriptEventKind
from modules.telephony.twilio_client import OriginatedCall


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@dataclass
class FakeOpenAIClient:
    """In-memory stand-in for :class:`modules.ai.openai_client.OpenAIClient`.

    The class provides the subset of methods exercised by ``AIService``
    plus the bench harness — ``complete``, ``stream``, ``stream_collected``,
    ``aclose``, and the ``model`` property.
    """

    model: str = "fake-gpt-4o"
    default_temperature: float = 0.4
    default_max_tokens: int = 320
    reply_text: str = (
        "Sure — would Tuesday at 10am work for a 15-minute walkthrough?"
    )
    per_call_latency_ms: int = 5
    raise_exc: Exception | None = None

    async def complete(
        self,
        messages: Iterable[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        user: str | None = None,
    ) -> ChatTurnResult:
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.per_call_latency_ms > 0:
            await asyncio.sleep(self.per_call_latency_ms / 1000.0)
        stats = ChatTurnStats(
            latency_ms=self.per_call_latency_ms,
            ttft_ms=self.per_call_latency_ms,
            prompt_tokens=42,
            completion_tokens=17,
            total_tokens=59,
            finish_reason="stop",
            model=model or self.model,
        )
        return ChatTurnResult(text=self.reply_text, stats=stats)

    async def stream(
        self,
        messages: Iterable[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        user: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        if self.raise_exc is not None:
            raise self.raise_exc
        first = True
        for word in self.reply_text.split():
            if self.per_call_latency_ms > 0:
                await asyncio.sleep(self.per_call_latency_ms / 1000.0 / 4)
            yield StreamChunk(delta=word + " ", is_first=first, is_final=False)
            first = False
        yield StreamChunk(
            delta="", is_first=False, is_final=True, finish_reason="stop"
        )

    async def stream_collected(
        self,
        messages: Iterable[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        user: str | None = None,
        on_first_token=None,
    ) -> ChatTurnResult:
        result = await self.complete(messages, model=model)
        if on_first_token is not None and not on_first_token.is_set():
            on_first_token.set()
        return result

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# LiveKit
# ---------------------------------------------------------------------------


class FakeLiveKitService:
    """Stand-in for ``modules.livekit.service.LiveKitService``.

    The fake mints tokens locally (so any latency benchmark we care
    about exercises the same JWT cost as production) and tracks created
    rooms in memory so tests can assert on side-effects.
    """

    def __init__(self, *, url: str = "wss://fake.livekit.cloud") -> None:
        self._url = url
        self.rooms: dict[str, RoomResponse] = {}
        self.deleted: list[str] = []

    @property
    def url(self) -> str:
        return self._url

    async def create_room(self, data: CreateRoomRequest) -> RoomResponse:
        room = RoomResponse(
            sid=f"RM_{uuid.uuid4().hex[:12]}",
            name=data.name,
            empty_timeout=data.empty_timeout or 300,
            max_participants=data.max_participants or 20,
            creation_time=int(time.time()),
            num_participants=0,
            metadata=data.metadata,
        )
        self.rooms[data.name] = room
        return room

    async def list_rooms(self, names: list[str] | None = None) -> list[RoomResponse]:
        if not names:
            return list(self.rooms.values())
        return [self.rooms[n] for n in names if n in self.rooms]

    async def get_room(self, name: str) -> RoomResponse:
        if name not in self.rooms:
            from modules.livekit.exceptions import RoomNotFoundError

            raise RoomNotFoundError(f"Room '{name}' not found")
        return self.rooms[name]

    async def delete_room(self, name: str) -> None:
        self.deleted.append(name)
        self.rooms.pop(name, None)

    def generate_token(self, data: TokenRequest) -> TokenResponse:
        ttl = timedelta(minutes=data.ttl_minutes or 60)
        return TokenResponse(
            token=f"fake.jwt.{uuid.uuid4().hex[:8]}",
            url=self._url,
            room=data.room,
            identity=data.identity,
            expires_at=datetime.now(timezone.utc) + ttl,
        )

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Deepgram
# ---------------------------------------------------------------------------


@dataclass
class FakeDeepgramSession:
    """Pretend Deepgram websocket. Emits a scripted event sequence."""

    events_to_emit: list[TranscriptEvent] = field(default_factory=list)
    sent_bytes: int = 0

    async def send_audio(self, pcm: bytes) -> None:
        self.sent_bytes += len(pcm)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        for ev in self.events_to_emit:
            await asyncio.sleep(0)  # let scheduler run
            yield ev

    async def close(self) -> None:
        return None


def script_speech_turn(
    *, partial_text: str = "I want", final_text: str = "I want a demo"
) -> list[TranscriptEvent]:
    """Build a realistic STT event sequence for one user turn."""

    return [
        TranscriptEvent(kind=TranscriptEventKind.SPEECH_STARTED, ts_ms=0),
        TranscriptEvent(
            kind=TranscriptEventKind.PARTIAL,
            text=partial_text,
            is_final=False,
            confidence=0.85,
            ts_ms=150,
        ),
        TranscriptEvent(
            kind=TranscriptEventKind.FINAL,
            text=final_text,
            is_final=True,
            confidence=0.95,
            ts_ms=600,
            speech_final=True,
        ),
        TranscriptEvent(kind=TranscriptEventKind.UTTERANCE_END, ts_ms=750),
    ]


# ---------------------------------------------------------------------------
# ElevenLabs
# ---------------------------------------------------------------------------


@dataclass
class FakeElevenLabsTTS:
    """Stand-in for :class:`modules.tts.elevenlabs_client.ElevenLabsTTS`."""

    sample_rate: int = 24000
    default_voice_id: str = "fake-voice"
    default_model_id: str = "eleven_turbo_v2_5"
    chunk_size: int = 4096
    chunks_per_sentence: int = 4
    per_chunk_delay_ms: int = 2

    async def stream_pcm(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        model_id: str | None = None,
    ) -> AsyncIterator[bytes]:
        for _ in range(self.chunks_per_sentence):
            if self.per_chunk_delay_ms > 0:
                await asyncio.sleep(self.per_chunk_delay_ms / 1000.0)
            yield b"\x00\x01" * (self.chunk_size // 2)

    async def list_voices(self):
        from modules.tts.schema import Voice

        return [
            Voice(voice_id=self.default_voice_id, name="Fake Voice"),
        ]


# ---------------------------------------------------------------------------
# Twilio
# ---------------------------------------------------------------------------


@dataclass
class FakeTwilioClient:
    """Stand-in for :class:`modules.telephony.twilio_client.TwilioClient`."""

    account_sid: str = "ACfake000000000000000000000000000"
    auth_mode: str = "auth_token"
    can_validate_signatures: bool = True
    phone_number: str = "+15551234567"
    public_base_url: str = "https://fake.test"
    livekit_sip_uri: str = "fake.sip.livekit.cloud"
    create_latency_ms: int = 3
    hangup_latency_ms: int = 2
    last_kwargs: dict[str, Any] = field(default_factory=dict)
    calls_created: list[OriginatedCall] = field(default_factory=list)

    async def create_call(self, **kwargs) -> OriginatedCall:
        self.last_kwargs = dict(kwargs)
        if self.create_latency_ms > 0:
            await asyncio.sleep(self.create_latency_ms / 1000.0)
        call = OriginatedCall(
            sid=f"CA{uuid.uuid4().hex}",
            status="queued",
            from_=kwargs.get("from_number") or self.phone_number,
            to=kwargs.get("to_number"),
        )
        self.calls_created.append(call)
        return call

    async def hangup(self, call_sid: str) -> None:
        if self.hangup_latency_ms > 0:
            await asyncio.sleep(self.hangup_latency_ms / 1000.0)

    def build_voice_twiml(
        self,
        *,
        room_name: str,
        caller_id: str | None = None,
        opening_say: str | None = None,
    ) -> str:
        opening = f"<Say>{opening_say}</Say>" if opening_say else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?><Response>'
            f"{opening}"
            f'<Dial answerOnBridge="true">'
            f"<Sip>sip:{room_name}@{self.livekit_sip_uri}</Sip>"
            "</Dial></Response>"
        )

    def validate_signature(self, **_kwargs) -> bool:
        return True
