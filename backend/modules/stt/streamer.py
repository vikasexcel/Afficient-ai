"""Bridge a LiveKit room into Deepgram for live transcription.

Mirrors :mod:`modules.tts.streamer` in structure:

* :meth:`STTStreamer.transcribe_for` — one-shot, time-boxed: join, transcribe
  for N seconds, return collected events. Used by the admin/test endpoint
  and the e2e script.
* :meth:`STTStreamer.open_session` — long-lived context manager that
  yields an :class:`STTSession` exposing ``events()`` and ``close()``.
  Intended for the conversation loop where the same session lives across
  many user turns.

The transport joins the room as a subscribe-only agent so it never
publishes audio — useful for running the STT agent alongside the TTS
agent in the same room without feedback loops.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from common.logging import get_logger
from config.settings import settings
from modules.livekit.exceptions import LiveKitError
from modules.livekit.schema import TokenRequest
from modules.livekit.service import LiveKitService
from modules.livekit.transport import AudioTransport
from modules.stt.deepgram_client import DeepgramSTT, DeepgramSession
from modules.stt.exceptions import STTStreamError
from modules.stt.schema import TranscriptEvent, TranscriptEventKind

log = get_logger("stt.streamer")


@dataclass
class STTStats:
    """Simple counters for an STT session — handy for benchmarks and tests."""

    frames_pushed: int = 0
    bytes_pushed: int = 0
    events_emitted: int = 0
    first_event_ms: int | None = None
    finals: int = 0
    partials: int = 0
    speech_started_events: int = 0
    utterance_end_events: int = 0
    events: list[TranscriptEvent] = field(default_factory=list)


class STTSession:
    """Owns a Deepgram session + the LiveKit transport pumping audio into it.

    Construct via :meth:`STTStreamer.open_session`. The session does **not**
    own the event dispatch loop — callers iterate :meth:`events` themselves
    so they can interleave logic (e.g. trigger TTS barge-in on
    ``SPEECH_STARTED``).

    The session is **reconnect-aware**: if the Deepgram websocket drops
    mid-call, :meth:`events` will silently transparently re-open a fresh
    socket (up to ``settings.STT_MAX_RECONNECT_ATTEMPTS`` times) and
    keep yielding events to the caller. The audio pump is rebound to
    the new socket so no PCM is lost beyond the reconnect window.
    """

    def __init__(
        self,
        *,
        transport: AudioTransport,
        deepgram: DeepgramSession,
        target_participant: str | None,
        room: str,
        reopen_session: "_ReopenFn | None" = None,
    ) -> None:
        self._transport = transport
        self._deepgram = deepgram
        self._target_participant = target_participant
        self._room = room
        self._stats = STTStats()
        self._pump_task: asyncio.Task[None] | None = None
        self._t0 = time.monotonic()
        self._closed = False
        # Callable that opens a fresh DeepgramSession bound to the
        # original sample rate / channels / language config. Injected
        # by :meth:`STTStreamer.open_session` so reconnect logic stays
        # in one place.
        self._reopen_session = reopen_session
        self._reconnects = 0

    @property
    def stats(self) -> STTStats:
        return self._stats

    @property
    def room(self) -> str:
        return self._room

    @property
    def reconnects(self) -> int:
        return self._reconnects

    async def _start_audio_pump(self) -> None:
        self._pump_task = asyncio.create_task(self._pump_audio())

    async def _pump_audio(self) -> None:
        try:
            async for frame in self._transport.iter_audio(
                participant_identity=self._target_participant
            ):
                try:
                    await self._deepgram.send_audio(frame.data)
                except STTStreamError:
                    # Don't bail — the events() coroutine will detect the
                    # socket closure and reconnect; once it rebinds
                    # _deepgram the next iteration will succeed.
                    log.warning(
                        "stt.streamer.send_failed_pending_reconnect",
                        room=self._room,
                    )
                    await asyncio.sleep(0.05)
                    continue
                self._stats.frames_pushed += 1
                self._stats.bytes_pushed += len(frame.data)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("stt.streamer.pump_failed", room=self._room)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        """Yield :class:`TranscriptEvent` records as Deepgram produces them.

        Each emitted event updates the session's :class:`STTStats` so
        ``session.stats`` is always live. Reconnects are transparent:
        callers see a continuous stream even if the Deepgram socket
        drops once or twice.
        """

        while True:
            try:
                async for event in self._deepgram.events():
                    if self._stats.first_event_ms is None:
                        self._stats.first_event_ms = int(
                            (time.monotonic() - self._t0) * 1000
                        )
                    self._stats.events_emitted += 1
                    if event.kind == TranscriptEventKind.FINAL:
                        self._stats.finals += 1
                    elif event.kind == TranscriptEventKind.PARTIAL:
                        self._stats.partials += 1
                    elif event.kind == TranscriptEventKind.SPEECH_STARTED:
                        self._stats.speech_started_events += 1
                    elif event.kind == TranscriptEventKind.UTTERANCE_END:
                        self._stats.utterance_end_events += 1
                    self._stats.events.append(event)
                    yield event
            except Exception:  # noqa: BLE001 — translated below
                log.exception(
                    "stt.streamer.events_iterator_failed", room=self._room
                )
                # fall through to reconnect logic

            if self._closed or self._reopen_session is None:
                return

            if not await self._reconnect():
                return

    async def _reconnect(self) -> bool:
        """Rebind ``self._deepgram`` to a fresh session, with backoff.

        Returns ``True`` if reconnection succeeded and the caller should
        keep iterating, ``False`` if we've exhausted the policy and the
        session is now terminal.
        """

        from config.settings import settings  # local import to avoid cycle

        max_attempts = max(0, settings.STT_MAX_RECONNECT_ATTEMPTS)
        backoff = settings.STT_RECONNECT_BACKOFF_SECONDS
        for attempt in range(1, max_attempts + 1):
            self._reconnects += 1
            try:
                await self._deepgram.close()
            except Exception:  # noqa: BLE001 — old socket is dead anyway
                pass
            log.warning(
                "stt.streamer.reconnecting",
                room=self._room,
                attempt=attempt,
                backoff_ms=int(backoff * 1000),
            )
            await asyncio.sleep(backoff)
            try:
                assert self._reopen_session is not None
                new_session = await self._reopen_session()
            except Exception:  # noqa: BLE001 — try again on next loop
                log.exception(
                    "stt.streamer.reconnect_failed",
                    room=self._room,
                    attempt=attempt,
                )
                backoff = min(backoff * 2, 8.0)
                continue
            self._deepgram = new_session
            log.info(
                "stt.streamer.reconnected",
                room=self._room,
                attempt=attempt,
            )
            return True
        log.error(
            "stt.streamer.reconnect_exhausted",
            room=self._room,
            attempts=max_attempts,
        )
        return False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await self._deepgram.close()
        except Exception:
            log.exception("stt.streamer.deepgram_close_failed")
        try:
            await self._transport.disconnect()
        except Exception:
            log.exception("stt.streamer.transport_close_failed")


# Type alias for the deferred session-opener supplied by the streamer.
from typing import Awaitable, Callable  # noqa: E402

_ReopenFn = Callable[[], Awaitable[DeepgramSession]]


class STTStreamer:
    """Bridges :class:`DeepgramSTT` to a LiveKit room as a subscribe-only agent."""

    # 48 kHz mono is what LiveKit's AudioStream emits by default for opus
    # tracks decoded server-side. Override per-session if you publish at a
    # different rate (the TTS publisher in this repo emits at 24 kHz).
    DEFAULT_SAMPLE_RATE = 48000
    DEFAULT_CHANNELS = 1

    def __init__(
        self,
        *,
        stt: DeepgramSTT,
        livekit: LiveKitService,
        agent_identity: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        self._stt = stt
        self._livekit = livekit
        self._agent_identity = agent_identity or settings.DEEPGRAM_STT_AGENT_IDENTITY
        self._agent_name = agent_name or settings.DEEPGRAM_STT_AGENT_NAME

    @asynccontextmanager
    async def open_session(
        self,
        *,
        room: str,
        target_participant: str | None = None,
        sample_rate: int | None = None,
        num_channels: int | None = None,
        language: str | None = None,
        interim_results: bool | None = None,
        agent_identity: str | None = None,
        agent_name: str | None = None,
    ) -> AsyncIterator[STTSession]:
        """Yield a live :class:`STTSession` for ``room``.

        ``sample_rate`` / ``num_channels`` must match what LiveKit will
        deliver to ``iter_audio`` for the target track. Browsers publish
        opus that LiveKit decodes to 48 kHz mono by default, which is the
        default here.
        """

        identity = agent_identity or self._agent_identity
        name = agent_name or self._agent_name
        rate = sample_rate or self.DEFAULT_SAMPLE_RATE
        channels = num_channels or self.DEFAULT_CHANNELS

        token = self._livekit.generate_token(
            TokenRequest(
                room=room,
                identity=identity,
                name=name,
                can_publish=False,
                can_subscribe=True,
                can_publish_data=False,
            )
        )
        transport = AudioTransport(
            token=token.token,
            url=token.url,
            sample_rate=rate,
            num_channels=channels,
        )
        try:
            await transport.connect(auto_publish=False)
        except LiveKitError as exc:
            raise STTStreamError(f"failed to connect STT agent: {exc}") from exc

        async with self._stt.open_session(
            sample_rate=rate,
            num_channels=channels,
            language=language,
            interim_results=interim_results,
        ) as deepgram:

            async def _reopen() -> DeepgramSession:
                """Re-open a fresh Deepgram session with the same config.

                Used by :meth:`STTSession._reconnect`. We bypass the
                context manager because the lifetime of the new socket
                is managed by ``STTSession`` (it closes the old one
                explicitly before swapping in this one).
                """

                cm = self._stt.open_session(
                    sample_rate=rate,
                    num_channels=channels,
                    language=language,
                    interim_results=interim_results,
                )
                # The context manager yields a session; ``__aenter__``
                # opens the socket and starts the reader task. We
                # deliberately don't ``__aexit__`` here — STTSession
                # closes via :meth:`DeepgramSession.close`.
                return await cm.__aenter__()

            session = STTSession(
                transport=transport,
                deepgram=deepgram,
                target_participant=target_participant,
                room=room,
                reopen_session=_reopen,
            )
            await session._start_audio_pump()  # noqa: SLF001
            log.info(
                "stt.streamer.session.opened",
                room=room,
                target=target_participant,
                sample_rate=rate,
            )
            try:
                yield session
            finally:
                await session.close()
                log.info("stt.streamer.session.closed", room=room)

    async def transcribe_for(
        self,
        *,
        room: str,
        duration_seconds: float,
        target_participant: str | None = None,
        sample_rate: int | None = None,
        num_channels: int | None = None,
        language: str | None = None,
        interim_results: bool | None = None,
    ) -> STTStats:
        """One-shot: open session, drain events for N seconds, close, return stats.

        Useful for smoke tests and the ``POST /stt/transcribe`` endpoint.
        For real-time conversation use :meth:`open_session` directly.
        """

        async with self.open_session(
            room=room,
            target_participant=target_participant,
            sample_rate=sample_rate,
            num_channels=num_channels,
            language=language,
            interim_results=interim_results,
        ) as session:
            try:
                await asyncio.wait_for(
                    self._drain_events(session), timeout=duration_seconds
                )
            except asyncio.TimeoutError:
                # Expected — we transcribe for a bounded window.
                pass
            return session.stats

    @staticmethod
    async def _drain_events(session: STTSession) -> None:
        async for _ in session.events():
            pass
