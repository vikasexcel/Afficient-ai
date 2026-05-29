"""Async Deepgram STT client.

Wraps :class:`deepgram.AsyncDeepgramClient` so the rest of the codebase
talks to a stable, vendor-agnostic surface:

    async with deepgram.open_session(sample_rate=48000) as session:
        await session.send_audio(pcm_bytes)
        async for event in session.events():
            ...
        await session.close()

Behind the scenes this manages a single Deepgram WebSocket connection and
a background task that pumps messages from the socket into an asyncio
queue, normalising them into :class:`TranscriptEvent` records.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from deepgram import AsyncDeepgramClient

from common.logging import get_logger
from config.settings import settings
from modules.stt.exceptions import (
    STTConfigError,
    STTProviderError,
    STTStreamError,
)
from modules.stt.schema import TranscriptEvent, TranscriptEventKind

log = get_logger("stt.deepgram")


_SENTINEL: object = object()


class DeepgramSession:
    """One live Deepgram WebSocket connection.

    Instances are produced by :meth:`DeepgramSTT.open_session` and should
    not be constructed directly. The session lifetime owns:

    * The underlying ``AsyncV1SocketClient`` websocket.
    * A background reader task that drains the socket into ``_queue``.
    * The wall-clock origin used to stamp ``TranscriptEvent.ts_ms``.
    """

    def __init__(
        self,
        *,
        socket: Any,
        socket_cm: Any,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._socket = socket
        self._socket_cm = socket_cm
        self._loop = loop
        self._queue: asyncio.Queue[TranscriptEvent | object] = asyncio.Queue(
            maxsize=1024
        )
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False
        self._t0 = time.monotonic()

    async def _start_reader(self) -> None:
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        try:
            async for msg in self._socket:
                event = self._normalise(msg)
                if event is None:
                    continue
                try:
                    self._queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Drop the oldest event so we don't stall the reader.
                    try:
                        self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    self._queue.put_nowait(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("stt.deepgram.reader_failed")
        finally:
            await self._queue.put(_SENTINEL)

    def _normalise(self, msg: Any) -> TranscriptEvent | None:
        type_name = getattr(msg, "type", None) or (
            msg.get("type") if isinstance(msg, dict) else None
        )
        ts_ms = int((time.monotonic() - self._t0) * 1000)

        if type_name == "Results":
            channel = getattr(msg, "channel", None)
            alts = getattr(channel, "alternatives", None) if channel else None
            if not alts:
                return None
            top = alts[0]
            text = (getattr(top, "transcript", "") or "").strip()
            is_final = bool(getattr(msg, "is_final", False))
            # Skip empty interim chatter — Deepgram emits a lot of these.
            if not text and not is_final:
                return None
            return TranscriptEvent(
                kind=(
                    TranscriptEventKind.FINAL
                    if is_final
                    else TranscriptEventKind.PARTIAL
                ),
                text=text,
                is_final=is_final,
                confidence=getattr(top, "confidence", None),
                ts_ms=ts_ms,
                speech_final=getattr(msg, "speech_final", None),
            )

        if type_name == "SpeechStarted":
            return TranscriptEvent(
                kind=TranscriptEventKind.SPEECH_STARTED,
                ts_ms=ts_ms,
            )

        if type_name == "UtteranceEnd":
            return TranscriptEvent(
                kind=TranscriptEventKind.UTTERANCE_END,
                ts_ms=ts_ms,
            )

        # Metadata / unknown — ignored.
        return None

    async def send_audio(self, pcm: bytes) -> None:
        """Push a PCM16 chunk to Deepgram. Safe to call from any task."""

        if self._closed:
            raise STTStreamError("session is closed")
        try:
            await self._socket.send_media(pcm)
        except Exception as exc:
            raise STTStreamError(f"send_media failed: {exc}") from exc

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        """Yield events until the session closes (provider or user-initiated)."""

        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            yield item  # type: ignore[misc]

    async def close(self) -> None:
        """Tell Deepgram we're done, wait for finalize, then tear down."""

        if self._closed:
            return
        self._closed = True
        try:
            await self._socket.send_close_stream()
        except Exception:
            log.exception("stt.deepgram.close_stream_failed")

        if self._reader_task is not None:
            # The reader exits when the socket closes; give it a moment.
            try:
                await asyncio.wait_for(self._reader_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except (asyncio.CancelledError, Exception):
                    pass

        try:
            await self._socket_cm.__aexit__(None, None, None)
        except Exception:
            log.exception("stt.deepgram.socket_close_failed")


class DeepgramSTT:
    """Thin async wrapper around the Deepgram live websocket SDK."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        language: str | None = None,
        interim_results: bool | None = None,
        vad_events: bool | None = None,
        endpointing_ms: int | None = None,
        utterance_end_ms: int | None = None,
        smart_format: bool | None = None,
        punctuate: bool | None = None,
    ) -> None:
        self._api_key = api_key or settings.DEEPGRAM_API_KEY
        if not self._api_key:
            raise STTConfigError("DEEPGRAM_API_KEY is not set")
        self._model = model or settings.DEEPGRAM_MODEL
        self._language = language or settings.DEEPGRAM_LANGUAGE
        self._interim_results = (
            interim_results
            if interim_results is not None
            else settings.DEEPGRAM_INTERIM_RESULTS
        )
        self._vad_events = (
            vad_events if vad_events is not None else settings.DEEPGRAM_VAD_EVENTS
        )
        self._endpointing_ms = (
            endpointing_ms
            if endpointing_ms is not None
            else settings.DEEPGRAM_ENDPOINTING_MS
        )
        self._utterance_end_ms = (
            utterance_end_ms
            if utterance_end_ms is not None
            else settings.DEEPGRAM_UTTERANCE_END_MS
        )
        self._smart_format = (
            smart_format
            if smart_format is not None
            else settings.DEEPGRAM_SMART_FORMAT
        )
        self._punctuate = (
            punctuate if punctuate is not None else settings.DEEPGRAM_PUNCTUATE
        )
        self._client = AsyncDeepgramClient(api_key=self._api_key)

    @asynccontextmanager
    async def open_session(
        self,
        *,
        sample_rate: int,
        num_channels: int = 1,
        language: str | None = None,
        interim_results: bool | None = None,
    ) -> AsyncIterator[DeepgramSession]:
        """Open a single live transcription session.

        ``sample_rate`` and ``num_channels`` must match the audio you send
        via :meth:`DeepgramSession.send_audio` — Deepgram cannot infer
        either from the raw PCM bytes.
        """

        lang = language or self._language
        interim = interim_results if interim_results is not None else self._interim_results

        try:
            socket_cm = self._client.listen.v1.connect(
                model=self._model,
                language=lang,
                encoding="linear16",
                sample_rate=sample_rate,
                channels=num_channels,
                interim_results=interim,
                vad_events=self._vad_events,
                endpointing=self._endpointing_ms,
                utterance_end_ms=str(self._utterance_end_ms),
                smart_format=self._smart_format,
                punctuate=self._punctuate,
            )
            socket = await socket_cm.__aenter__()
        except Exception as exc:
            log.exception("stt.deepgram.connect_failed")
            raise STTProviderError(f"deepgram connect failed: {exc}") from exc

        loop = asyncio.get_running_loop()
        session = DeepgramSession(
            socket=socket,
            socket_cm=socket_cm,
            loop=loop,
        )
        await session._start_reader()  # noqa: SLF001 — internal handshake
        log.info(
            "stt.deepgram.session.opened",
            model=self._model,
            language=lang,
            sample_rate=sample_rate,
            channels=num_channels,
        )

        try:
            yield session
        finally:
            await session.close()
            log.info("stt.deepgram.session.closed")
