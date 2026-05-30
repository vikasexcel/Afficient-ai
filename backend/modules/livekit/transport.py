"""WebRTC audio transport for joining a LiveKit room as a backend agent.

The transport is intentionally narrow: it owns the lifetime of a
``livekit.rtc.Room`` connection and provides two primitives:

* :py:meth:`AudioTransport.publish_audio` — push PCM frames out to the room.
* :py:meth:`AudioTransport.iter_audio` — receive PCM frames from a specific
  remote participant (or any remote, if none specified).

Higher-level features (STT, TTS, LLM orchestration) consume these primitives
and live in their own modules.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator

from livekit import rtc

from common.logging import get_logger
from config.settings import settings
from modules.livekit.exceptions import TransportError

log = get_logger("livekit.transport")


DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 1


@dataclass
class AudioFrame:
    """Plain-data wrapper around a PCM frame so callers don't depend on rtc.*."""

    data: bytes
    sample_rate: int
    num_channels: int
    samples_per_channel: int
    participant_identity: str | None = None


@dataclass
class _TransportState:
    room: rtc.Room | None = None
    source: rtc.AudioSource | None = None
    track: rtc.LocalAudioTrack | None = None
    queues: dict[str, asyncio.Queue[AudioFrame]] = field(default_factory=dict)
    closed: bool = False


class AudioTransport:
    """Connects to a LiveKit room and bridges audio in both directions."""

    def __init__(
        self,
        *,
        token: str,
        url: str | None = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        num_channels: int = DEFAULT_CHANNELS,
        publish_track_name: str = "agent-audio",
    ) -> None:
        self._token = token
        self._url = url or settings.LIVEKIT_URL
        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._publish_track_name = publish_track_name
        self._state = _TransportState()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, *, auto_publish: bool = True) -> None:
        if self._state.room is not None:
            raise TransportError("transport already connected")

        room = rtc.Room()
        self._wire_events(room)

        try:
            await room.connect(self._url, self._token)
        except Exception as exc:
            log.exception("livekit.transport.connect_failed", url=self._url)
            raise TransportError(f"connect failed: {exc}") from exc

        self._state.room = room
        log.info(
            "livekit.transport.connected",
            url=self._url,
            room=getattr(room, "name", None),
            local_sid=getattr(room.local_participant, "sid", None),
        )

        if auto_publish:
            await self._publish_local_track()

    async def disconnect(self) -> None:
        if self._state.closed:
            return
        self._state.closed = True

        room = self._state.room
        self._state.room = None
        if room is not None:
            try:
                await room.disconnect()
            except Exception:  # pragma: no cover
                log.exception("livekit.transport.disconnect_failed")
            log.info("livekit.transport.disconnected")

        for q in self._state.queues.values():
            await q.put(_SENTINEL)  # type: ignore[arg-type]
        self._state.queues.clear()
        self._state.source = None
        self._state.track = None

    async def __aenter__(self) -> "AudioTransport":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Outbound audio
    # ------------------------------------------------------------------

    async def _publish_local_track(self) -> None:
        room = self._require_room()
        source = rtc.AudioSource(self._sample_rate, self._num_channels)
        track = rtc.LocalAudioTrack.create_audio_track(
            self._publish_track_name, source
        )
        options = rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_MICROPHONE,
        )
        try:
            await room.local_participant.publish_track(track, options)
        except Exception as exc:
            log.exception("livekit.transport.publish_failed")
            raise TransportError(f"publish failed: {exc}") from exc

        self._state.source = source
        self._state.track = track
        log.info(
            "livekit.transport.track_published",
            name=self._publish_track_name,
            sample_rate=self._sample_rate,
            channels=self._num_channels,
        )

    async def publish_audio(
        self,
        pcm: bytes,
        *,
        samples_per_channel: int | None = None,
    ) -> None:
        """Send a single PCM16 frame to the room.

        ``samples_per_channel`` defaults to ``len(pcm) // 2 // channels``
        (assumes 16-bit PCM).
        """

        if self._state.source is None:
            raise TransportError("local audio track not published")

        if samples_per_channel is None:
            samples_per_channel = len(pcm) // 2 // self._num_channels

        frame = rtc.AudioFrame(
            data=pcm,
            sample_rate=self._sample_rate,
            num_channels=self._num_channels,
            samples_per_channel=samples_per_channel,
        )
        try:
            await self._state.source.capture_frame(frame)
        except Exception as exc:
            log.exception("livekit.transport.capture_failed")
            raise TransportError(f"capture frame failed: {exc}") from exc

    async def wait_for_playout(self) -> None:
        """Block until all queued PCM has been sent over the wire.

        LiveKit's ``AudioSource`` buffers frames; disconnecting before this
        drains will cut the tail of the utterance.
        """

        if self._state.source is None:
            return
        try:
            await self._state.source.wait_for_playout()
        except Exception:
            log.exception("livekit.transport.wait_for_playout_failed")

    def clear_audio_buffer(self) -> int:
        """Drop every PCM frame still queued on the local AudioSource.

        Critical for barge-in: cancelling the TTS pump only stops *new*
        frames from being submitted; the LiveKit ``AudioSource`` still
        plays out whatever it already has queued (~hundreds of ms). This
        method drains that queue immediately so the agent goes silent
        within one RTC round-trip after the user starts speaking.

        Returns the number of milliseconds of audio that was dropped (0
        if nothing was queued or the source doesn't expose the API).
        """

        source = self._state.source
        if source is None:
            return 0
        # `queued_duration` returns seconds (float) in the livekit-rtc
        # Python SDK; convert to ms for caller convenience.
        queued_ms = 0
        try:
            queued_seconds = getattr(source, "queued_duration", 0.0) or 0.0
            queued_ms = int(queued_seconds * 1000)
        except Exception:  # pragma: no cover — defensive
            queued_ms = 0
        try:
            source.clear_queue()
        except Exception:
            log.exception("livekit.transport.clear_queue_failed")
            return 0
        if queued_ms > 0:
            log.info(
                "livekit.transport.audio_buffer_cleared",
                queued_ms=queued_ms,
            )
        return queued_ms

    # ------------------------------------------------------------------
    # Inbound audio
    # ------------------------------------------------------------------

    async def iter_audio(
        self,
        participant_identity: str | None = None,
    ) -> AsyncIterator[AudioFrame]:
        """Yield inbound audio frames.

        If ``participant_identity`` is given, only frames from that
        participant are emitted; otherwise frames from any remote
        participant are interleaved.
        """

        key = participant_identity or "*"
        queue: asyncio.Queue[AudioFrame] = self._state.queues.setdefault(
            key, asyncio.Queue(maxsize=256)
        )

        while True:
            frame = await queue.get()
            if frame is _SENTINEL:  # type: ignore[comparison-overlap]
                return
            yield frame

    # ------------------------------------------------------------------
    # Event wiring
    # ------------------------------------------------------------------

    def _wire_events(self, room: rtc.Room) -> None:
        @room.on("track_subscribed")
        def _on_track_subscribed(
            track: rtc.Track,
            publication: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            log.info(
                "livekit.transport.track_subscribed",
                participant=participant.identity,
                track_sid=track.sid,
            )
            asyncio.create_task(self._pump_remote_audio(track, participant))

        @room.on("participant_disconnected")
        def _on_participant_disconnected(p: rtc.RemoteParticipant) -> None:
            log.info(
                "livekit.transport.participant_disconnected",
                identity=p.identity,
            )

        @room.on("disconnected")
        def _on_disconnected(*_: object) -> None:
            log.info("livekit.transport.room_disconnected")

    async def _pump_remote_audio(
        self,
        track: rtc.Track,
        participant: rtc.RemoteParticipant,
    ) -> None:
        try:
            stream = rtc.AudioStream(track)
            async for event in stream:
                frame = event.frame
                wrapped = AudioFrame(
                    data=bytes(frame.data),
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                    samples_per_channel=frame.samples_per_channel,
                    participant_identity=participant.identity,
                )
                await self._fanout(wrapped)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "livekit.transport.remote_pump_failed",
                participant=participant.identity,
            )

    async def _fanout(self, frame: AudioFrame) -> None:
        identity = frame.participant_identity or ""
        targets = []
        if identity in self._state.queues:
            targets.append(self._state.queues[identity])
        if "*" in self._state.queues:
            targets.append(self._state.queues["*"])
        for q in targets:
            if q.full():
                # Drop the oldest frame to keep latency bounded.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await q.put(frame)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_room(self) -> rtc.Room:
        if self._state.room is None:
            raise TransportError("transport not connected")
        return self._state.room


_SENTINEL: object = object()
