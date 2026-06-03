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
from dataclasses import asdict, dataclass
from typing import AsyncIterator

from common.logging import get_logger
from config.settings import settings
from modules.livekit.exceptions import LiveKitError
from modules.livekit.schema import TokenRequest
from modules.livekit.service import LiveKitService
from modules.livekit.transport import AudioTransport
from modules.tts.elevenlabs_client import ElevenLabsTTS
from modules.tts.exceptions import TTSStreamError

# `InterruptResult` is forward-declared below; the import block stays
# import-cycle-safe because modules.ai.recovery is imported lazily.

log = get_logger("tts.streamer")


# 20ms frames are a good compromise: low enough latency for conversation,
# large enough to keep the per-frame overhead modest.
_FRAME_MS = 20


@dataclass
class PumpStats:
    """Per-utterance timing breakdown captured inside :meth:`TTSStreamer._pump`.

    All times are milliseconds measured from the moment ``_pump`` is entered.
    Useful for diagnosing whether latency lives in the upstream TTS provider,
    the publish path into LiveKit, or both.
    """

    bytes_streamed: int
    ttfb_ms: int
    first_frame_pub_ms: int
    stream_end_ms: int


@dataclass
class SpeakStats:
    """End-to-end timing for a single ``speak_into_room`` call.

    All ``*_ms`` fields are wall-clock milliseconds; the ``ttfb_ms`` /
    ``first_frame_pub_ms`` / ``stream_end_ms`` values are measured relative
    to the start of the pump phase (i.e. after connect), so they isolate
    the upstream TTS provider and publish path from connection setup.
    """

    bytes_streamed: int
    token_mint_ms: int
    connect_ms: int
    ttfb_ms: int
    first_frame_pub_ms: int
    stream_end_ms: int
    playout_wait_ms: int
    disconnect_ms: int
    total_ms: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    def timings(self) -> dict[str, int]:
        """Latency-only view (drops ``bytes_streamed``) for SpeakResponse."""

        return {k: v for k, v in asdict(self).items() if k.endswith("_ms")}


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

    @property
    def agent_identity(self) -> str:
        return self._agent_identity

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
    ) -> SpeakStats:
        """Join, speak, disconnect.

        Returns a :class:`SpeakStats` with a per-stage timing breakdown so
        callers can attribute latency to token minting, LiveKit connect,
        ElevenLabs time-to-first-byte, the publish path, playout drain, and
        disconnect.
        """

        identity = agent_identity or self._agent_identity
        name = agent_name or self._agent_name

        t_total_start = time.monotonic()

        t0 = time.monotonic()
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
        token_mint_ms = int((time.monotonic() - t0) * 1000)

        transport = AudioTransport(
            token=token.token,
            url=token.url,
            sample_rate=self._tts.sample_rate,
            num_channels=1,
            publish_track_name="tts-output",
        )

        t0 = time.monotonic()
        try:
            await transport.connect()
        except LiveKitError as exc:
            raise TTSStreamError(f"failed to connect agent: {exc}") from exc
        connect_ms = int((time.monotonic() - t0) * 1000)

        pump_stats: PumpStats | None = None
        playout_wait_ms = 0
        try:
            pump_stats = await self._pump(
                transport=transport,
                text=text,
                voice_id=voice_id,
                model_id=model_id,
            )
            # Wait until LiveKit has actually sent every queued frame; without
            # this the tail of the utterance is dropped when we disconnect.
            t0 = time.monotonic()
            await transport.wait_for_playout()
            playout_wait_ms = int((time.monotonic() - t0) * 1000)
        finally:
            t0 = time.monotonic()
            await transport.disconnect()
            disconnect_ms = int((time.monotonic() - t0) * 1000)

        total_ms = int((time.monotonic() - t_total_start) * 1000)

        stats = SpeakStats(
            bytes_streamed=pump_stats.bytes_streamed if pump_stats else 0,
            token_mint_ms=token_mint_ms,
            connect_ms=connect_ms,
            ttfb_ms=pump_stats.ttfb_ms if pump_stats else 0,
            first_frame_pub_ms=pump_stats.first_frame_pub_ms if pump_stats else 0,
            stream_end_ms=pump_stats.stream_end_ms if pump_stats else 0,
            playout_wait_ms=playout_wait_ms,
            disconnect_ms=disconnect_ms,
            total_ms=total_ms,
        )

        log.info(
            "tts.speak.done",
            room=room,
            identity=identity,
            **stats.as_dict(),
        )
        return stats

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
    ) -> PumpStats:
        """Bridge ElevenLabs PCM into the LiveKit room with one retry on
        upstream failure *before any audio has been published*.

        If the provider fails mid-utterance the lead has already heard
        the leading half of the sentence — re-trying would either replay
        that audio (bad) or start a new sentence (worse). In that case
        we surface :class:`TTSStreamError` so the orchestrator can speak
        a recovery line instead.
        """

        from modules.ai.recovery import RetryPolicy, with_retry  # avoid cycle

        bytes_per_frame = (self._tts.sample_rate * _FRAME_MS // 1000) * 2  # s16le
        samples_per_frame = bytes_per_frame // 2
        pump_start = time.monotonic()

        async def _one_attempt() -> PumpStats:
            buf = bytearray()
            total = 0
            ttfb_ms = -1
            first_frame_pub_ms = -1
            try:
                async for chunk in self._tts.stream_pcm(
                    text, voice_id=voice_id, model_id=model_id
                ):
                    if ttfb_ms < 0 and chunk:
                        ttfb_ms = int((time.monotonic() - pump_start) * 1000)
                    buf.extend(chunk)
                    total += len(chunk)
                    while len(buf) >= bytes_per_frame:
                        frame = bytes(buf[:bytes_per_frame])
                        del buf[:bytes_per_frame]
                        await transport.publish_audio(
                            frame, samples_per_channel=samples_per_frame
                        )
                        if first_frame_pub_ms < 0:
                            first_frame_pub_ms = int(
                                (time.monotonic() - pump_start) * 1000
                            )

                if buf:
                    pad = bytes_per_frame - len(buf)
                    frame = bytes(buf) + (b"\x00" * pad)
                    await transport.publish_audio(
                        frame, samples_per_channel=samples_per_frame
                    )
                    if first_frame_pub_ms < 0:
                        first_frame_pub_ms = int(
                            (time.monotonic() - pump_start) * 1000
                        )

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # If we've already pushed audio this is fatal — bail out
                # with the partial stats so the caller can record what
                # was heard before the cut.
                if first_frame_pub_ms >= 0:
                    raise TTSStreamError(
                        f"upstream tts failed mid-utterance: {exc}"
                    ) from exc
                # Nothing has played yet — re-raise the raw exception so
                # the retry policy can decide whether to try again.
                raise

            stream_end_ms = int((time.monotonic() - pump_start) * 1000)
            audio_duration_ms = int(
                total / max(self._tts.sample_rate * 2, 1) * 1000
            )
            log.info(
                "tts.TTS_AUDIO_DURATION",
                chars=len(text),
                bytes_streamed=total,
                audio_duration_ms=audio_duration_ms,
                stream_end_ms=stream_end_ms,
            )
            return PumpStats(
                bytes_streamed=total,
                ttfb_ms=max(ttfb_ms, 0),
                first_frame_pub_ms=max(first_frame_pub_ms, 0),
                stream_end_ms=stream_end_ms,
            )

        try:
            return await with_retry(
                _one_attempt,
                RetryPolicy(
                    max_attempts=max(1, settings.TTS_MAX_ATTEMPTS),
                    base_backoff_seconds=settings.TTS_RETRY_BACKOFF_SECONDS,
                    retry_on=(TTSStreamError, Exception),
                ),
                label="tts.pump",
            )
        except asyncio.CancelledError:
            raise
        except TTSStreamError:
            raise
        except Exception as exc:
            raise TTSStreamError(f"failed to push audio: {exc}") from exc


class BargeInInterrupted(Exception):
    """Raised by :meth:`TTSSession.speak` when an utterance is cut short.

    Carries the partial :class:`PumpStats` collected up to the interrupt
    point so callers can still surface latency / byte counts.
    """

    def __init__(self, partial: PumpStats | None = None) -> None:
        super().__init__("tts speech interrupted")
        self.partial = partial


@dataclass
class InterruptResult:
    """What :meth:`TTSSession.interrupt` returns.

    ``silence_latency_ms`` is the wall-clock time from the moment
    ``interrupt()`` was called until the audio buffer was actually
    cleared and the pump task ended. ``dropped_buffer_ms`` is how much
    queued PCM had to be discarded from LiveKit's local audio source.
    """

    silence_latency_ms: int
    dropped_buffer_ms: int
    was_speaking: bool


class TTSSession:
    """Handle to a long-lived agent connection.

    A session can be **interrupted** mid-utterance to support conversational
    barge-in: while :meth:`speak` is running, calling :meth:`interrupt`
    cancels the active pump task, clears LiveKit's queued PCM, and returns
    an :class:`InterruptResult` with the silence latency. ``speak`` then
    raises :class:`BargeInInterrupted` so the orchestrator knows the agent
    went silent before the planned utterance finished.
    """

    def __init__(self, *, streamer: TTSStreamer, transport: AudioTransport) -> None:
        self._streamer = streamer
        self._transport = transport
        self._current_task: asyncio.Task[PumpStats] | None = None
        self._interrupted = False
        self._interrupt_lock = asyncio.Lock()

    async def wait_for_human(
        self,
        *,
        exclude: set[str] | None = None,
        timeout: float = 30.0,
    ) -> str | None:
        """Block until the human caller joins the room (or ``timeout``).

        Used by the orchestrator to avoid speaking the opening line into
        an empty room before the PSTN leg has been answered and bridged
        into LiveKit. Returns the human participant identity or ``None``.
        """

        return await self._transport.wait_for_remote(
            exclude=exclude, timeout=timeout
        )

    @property
    def is_speaking(self) -> bool:
        """``True`` while a :meth:`speak` call is actively pushing audio."""

        return self._current_task is not None and not self._current_task.done()

    async def speak(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        model_id: str | None = None,
        wait_for_playout: bool = True,
    ) -> PumpStats:
        """Speak ``text`` into the room.

        Raises :class:`BargeInInterrupted` if :meth:`interrupt` is called
        before this call returns naturally. ``wait_for_playout`` is skipped
        on interruption so the caller can hand the microphone back to the
        user without waiting for LiveKit's internal buffer to drain.
        """

        if self.is_speaking:
            raise RuntimeError("TTSSession is already speaking")
        self._interrupted = False

        task: asyncio.Task[PumpStats] = asyncio.create_task(
            self._streamer._pump(  # noqa: SLF001 — same module
                transport=self._transport,
                text=text,
                voice_id=voice_id,
                model_id=model_id,
            )
        )
        self._current_task = task
        try:
            stats = await task
        except asyncio.CancelledError:
            # Re-raise as a typed signal so callers can distinguish a
            # barge-in from a "real" cancellation propagating up the loop.
            raise BargeInInterrupted(partial=None) from None
        finally:
            self._current_task = None

        if wait_for_playout and not self._interrupted:
            await self._transport.wait_for_playout()
        return stats

    async def interrupt(self) -> "InterruptResult":
        """Cancel the in-flight :meth:`speak` (barge-in).

        Idempotent. Safe to call concurrently with ``speak``; the lock
        protects against double-cancellation when two STT events arrive
        back-to-back. After cancelling the pump we also tell the
        underlying LiveKit AudioSource to drop any frames it still has
        queued so the lead hears silence *immediately* rather than a
        few hundred ms of trailing audio.

        Returns an :class:`InterruptResult`. Always returns a result even
        if there was nothing to interrupt — the orchestrator records the
        no-op into its metrics so we can detect spurious VAD events.
        """

        t0 = time.monotonic()
        async with self._interrupt_lock:
            task = self._current_task
            was_speaking = task is not None and not task.done()
            if was_speaking:
                self._interrupted = True
                task.cancel()  # type: ignore[union-attr]
                try:
                    await task  # type: ignore[arg-type]
                except (asyncio.CancelledError, BargeInInterrupted, Exception):
                    # Whatever the pump raised, we just want it gone.
                    pass
            # Always clear the local AudioSource queue — even if there
            # was no in-flight speak the buffer may still hold the tail
            # of a previous utterance.
            dropped_buffer_ms = self._transport.clear_audio_buffer()
            silence_latency_ms = int((time.monotonic() - t0) * 1000)
            return InterruptResult(
                silence_latency_ms=silence_latency_ms,
                dropped_buffer_ms=dropped_buffer_ms,
                was_speaking=was_speaking,
            )
