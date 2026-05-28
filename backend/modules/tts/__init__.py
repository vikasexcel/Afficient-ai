"""Text-to-speech integration (ElevenLabs) with LiveKit streaming.

Exposes:
  * :class:`ElevenLabsTTS` — async wrapper around the ElevenLabs SDK that
    yields raw PCM audio chunks.
  * :class:`TTSStreamer` — bridges TTS output into a LiveKit room as an
    agent participant using the existing :class:`AudioTransport`.
  * REST API at ``/api/v1/tts`` for one-shot speech-into-room calls and
    voice catalog lookup.
"""
