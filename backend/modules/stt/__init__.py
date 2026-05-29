"""Speech-to-text integration (Deepgram) with LiveKit ingestion.

This module mirrors the structure of :mod:`modules.tts`:

* :class:`DeepgramSTT` — async wrapper around the Deepgram SDK that opens
  a live websocket and normalises Deepgram messages into our own
  ``TranscriptEvent`` shape.
* :class:`STTStreamer` — joins a LiveKit room as a subscribe-only agent,
  pumps inbound audio frames from a target participant into Deepgram, and
  yields normalised transcript events.

The barge-in interaction lives at the call site: subscribers iterate
``STTSession.events()`` and, on ``TranscriptEventKind.SPEECH_STARTED``,
call :meth:`modules.tts.streamer.TTSSession.interrupt` to stop the
currently-playing agent utterance.
"""
