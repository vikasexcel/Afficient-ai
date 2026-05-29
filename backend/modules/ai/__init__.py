"""GPT-4o conversation engine.

This package implements the AI brain that sits between Deepgram STT and
ElevenLabs TTS. The public surface is intentionally small:

* :class:`modules.ai.openai_client.OpenAIClient` — thin async wrapper around
  the official OpenAI SDK, exposing chunked streaming and structured
  metrics (latency, token usage).
* :class:`modules.ai.memory.ConversationMemory` — Redis-backed rolling
  message history keyed by ``call_id``.
* :class:`modules.ai.qualification.QualificationTracker` — incremental
  BANT / MEDDICC state machine that updates as the agent talks.
* :class:`modules.ai.service.AIService` — high-level facade used by the
  HTTP router and the conversation orchestrator. Wraps the client,
  memory, qualification, and persistence into one ``respond()`` call.
* :class:`modules.ai.orchestrator.ConversationOrchestrator` — wires
  STT → AIService → TTS inside a single LiveKit room with barge-in.
"""

from modules.ai.exceptions import (
    AIConfigError,
    AIError,
    AIProviderError,
    AIQuotaError,
    AIRateLimitError,
    AITimeoutError,
)
from modules.ai.qualification import QualificationFramework

__all__ = [
    "AIConfigError",
    "AIError",
    "AIProviderError",
    "AIQuotaError",
    "AIRateLimitError",
    "AITimeoutError",
    "QualificationFramework",
]
