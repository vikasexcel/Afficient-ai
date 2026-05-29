"""AI module exceptions.

The router translates these into HTTPException via their ``status_code``
attribute so callers see stable error semantics regardless of which LLM
provider is configured.
"""

from __future__ import annotations


class AIError(Exception):
    """Base class for any AI/LLM failure."""

    status_code: int = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class AIConfigError(AIError):
    """Misconfiguration (missing API key, invalid model name, ...)."""

    status_code = 500


class AIProviderError(AIError):
    """Upstream LLM provider returned an error or invalid payload."""

    status_code = 502


class AIRateLimitError(AIError):
    """Provider rate-limited us (HTTP 429). Caller should back off."""

    status_code = 429


class AIQuotaError(AIError):
    """Account out of quota or billing issue."""

    status_code = 402


class AITimeoutError(AIError):
    """Provider call exceeded :data:`config.settings.OPENAI_TIMEOUT_SECONDS`."""

    status_code = 504


class AIMemoryError(AIError):
    """Redis backed conversation memory operation failed."""

    status_code = 502
