"""Bridge ElevenLabs TTS into a LiveKit room.

The streamer joins a room as an agent participant, publishes a microphone
track, then pushes PCM frames from ElevenLabs into ``AudioTransport`` until
the utterance ends. It supports two modes:

* **One-shot** (:meth:`TTSStreamer.speak_into_room`) — join, speak, leave.
  Best for stateless "say this" calls.
* **Long-lived session** (:meth:`TTSStreamer.open_session`) — keep the
  agent in the room across multiple utterances. Best for conversational
  agents to avoid reconnect overhead per turn.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from common.logging import get_logger
from config.settings import settings
from modules.livekit.exceptions import LiveKitError
from modules.livekit.schema import TokenRequest
from modules.livekit.service import LiveKitService
from modules.livekit.transport import AudioTransport
from modules.tts.elevenlabs_client import ElevenLabsTTS
from modules.tts.exceptions import TTSStreamError

log = get_logger("tts.streamer")


# 20ms frames are a good compromise: low enough latency for conversation,
# large enough to keep the per-frame overhead modest.
_FRAME_MS = 20


class TTSStreamer:
    """Bridges :class:`ElevenLabsTTS` output into a LiveKit room."""

    def __init__(
        self,
        *,
        tts: ElevenLabsTTS,
        livekit: LiveKitService,
        agent_identity: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        self._tts = tts
        self._livekit = livekit
        self._agent_identity = agent_identity or settings.ELEVENLABS_AGENT_IDENTITY
        self._agent_name = agent_name or settings.ELEVENLABS_AGENT_NAME

    # ------------------------------------------------------------------
    # One-shot API
    # ------------------------------------------------------------------

    async def speak_into_room(
        self,
        *,
        room: str,
        text: str,
        voice_id: str | None = None,
        model_id: str | None = None,
        agent_identity: str | None = None,
        agent_name: str | None = None,
    ) -> tuple[int, int]:
        """Join, speak, disconnect.

        Returns ``(bytes_streamed, duration_ms)`` where the byte count is the
        total PCM bytes pushed and the duration is wall-clock time spent in
        the room.
        """

        identity = agent_identity or self._agent_identity
        name = agent_name or self._agent_name

        token = self._livekit.generate_token(
            TokenRequest(
                room=room,
                identity=identity,
                name=name,
                can_publish=True,
                can_subscribe=False,
                can_publish_data=False,
            )
        )

        start = time.monotonic()
        transport = AudioTransport(
            token=token.token,
            url=token.url,
            sample_rate=self._tts.sample_rate,
            num_channels=1,
            publish_track_name="tts-output",
        )

        try:
            await transport.connect()
        except LiveKitError as exc:
            raise TTSStreamError(f"failed to connect agent: {exc}") from exc

        try:
            bytes_streamed = await self._pump(
                transport=transport,
                text=text,
                voice_id=voice_id,
                model_id=model_id,
            )
            # Wait until LiveKit has actually sent every queued frame; without
            # this the tail of the utterance is dropped when we disconnect.
            await transport.wait_for_playout()
        finally:
            await transport.disconnect()

        duration_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "tts.speak.done",
            room=room,
            identity=identity,
            bytes=bytes_streamed,
            duration_ms=duration_ms,
        )
        return bytes_streamed, duration_ms

    # ------------------------------------------------------------------
    # Long-lived session
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def open_session(
        self,
        *,
        room: str,
        agent_identity: str | None = None,
        agent_name: str | None = None,
    ) -> AsyncIterator["TTSSession"]:
        """Context manager that keeps an agent connected across utterances."""

        identity = agent_identity or self._agent_identity
        name = agent_name or self._agent_name

        token = self._livekit.generate_token(
            TokenRequest(
                room=room,
                identity=identity,
                name=name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        transport = AudioTransport(
            token=token.token,
            url=token.url,
            sample_rate=self._tts.sample_rate,
            num_channels=1,
            publish_track_name="tts-output",
        )
        try:
            await transport.connect()
        except LiveKitError as exc:
            raise TTSStreamError(f"failed to open session: {exc}") from exc

        session = TTSSession(streamer=self, transport=transport)
        try:
            yield session
        finally:
            await transport.disconnect()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _pump(
        self,
        *,
        transport: AudioTransport,
        text: str,
        voice_id: str | None,
        model_id: str | None,
    ) -> int:
        bytes_per_frame = (self._tts.sample_rate * _FRAME_MS // 1000) * 2  # s16le
        samples_per_frame = bytes_per_frame // 2

        buf = bytearray()
        total = 0
        try:
            async for chunk in self._tts.stream_pcm(
                text, voice_id=voice_id, model_id=model_id
            ):
                buf.extend(chunk)
                total += len(chunk)
                while len(buf) >= bytes_per_frame:
                    frame = bytes(buf[:bytes_per_frame])
                    del buf[:bytes_per_frame]
                    await transport.publish_audio(
                        frame, samples_per_channel=samples_per_frame
                    )

            # Flush a final partial frame, padded with silence so the listener
            # doesn't hear the buffer cut mid-sample.
            if buf:
                pad = bytes_per_frame - len(buf)
                frame = bytes(buf) + (b"\x00" * pad)
                await transport.publish_audio(
                    frame, samples_per_channel=samples_per_frame
                )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise TTSStreamError(f"failed to push audio: {exc}") from exc

        return total


class TTSSession:
    """Handle to a long-lived agent connection."""

    def __init__(self, *, streamer: TTSStreamer, transport: AudioTransport) -> None:
        self._streamer = streamer
        self._transport = transport

    async def speak(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        model_id: str | None = None,
        wait_for_playout: bool = True,
    ) -> int:
        bytes_streamed = await self._streamer._pump(
            transport=self._transport,
            text=text,
            voice_id=voice_id,
            model_id=model_id,
        )
        if wait_for_playout:
            await self._transport.wait_for_playout()
        return bytes_streamed
