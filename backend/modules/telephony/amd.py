"""Answering Machine Detection (AMD) service.

Provider-agnostic classification of *who/what* answered an outbound call so
the call flow can decide whether to run the AI conversation (human), drop a
pre-recorded voicemail (machine), or fall back (unknown).

Design
------
The canonical result vocabulary is intentionally tiny and stable::

    human | voicemail | unknown

Each telephony provider reports its own raw answer label (Twilio's
``AnsweredBy``: ``human`` / ``machine_start`` / ``machine_end_beep`` / ...).
A *provider mapper* translates that raw label into the canonical vocabulary.
New providers (e.g. a future LiveKit/SIP AMD, or a third-party AMD vendor)
register a mapper via :func:`register_provider` without touching callers — the
rest of the codebase only ever sees :class:`AMDResult`.

This module is pure (no DB / network) so it is trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

# --------------------------------------------------------------------------- #
# Canonical result vocabulary
# --------------------------------------------------------------------------- #

AMD_HUMAN = "human"
AMD_VOICEMAIL = "voicemail"
AMD_UNKNOWN = "unknown"

CANONICAL_RESULTS = frozenset({AMD_HUMAN, AMD_VOICEMAIL, AMD_UNKNOWN})


@dataclass
class AMDResult:
    """Provider-agnostic answer classification.

    ``result`` is one of :data:`AMD_HUMAN` / :data:`AMD_VOICEMAIL` /
    :data:`AMD_UNKNOWN`. ``confidence`` is a best-effort 0..1 score; providers
    that don't expose one report ``0.0``. ``raw`` preserves the original
    provider label for diagnostics / auditing.
    """

    result: str = AMD_UNKNOWN
    confidence: float = 0.0
    raw: str | None = None
    provider: str = "unknown"

    @property
    def is_human(self) -> bool:
        return self.result == AMD_HUMAN

    @property
    def is_voicemail(self) -> bool:
        return self.result == AMD_VOICEMAIL

    def as_dict(self) -> dict:
        return {
            "result": self.result,
            "confidence": self.confidence,
            "raw": self.raw,
            "provider": self.provider,
        }


# A provider mapper maps a normalised raw label -> canonical result.
ProviderMapper = Callable[[str], str]


def _normalize(label: str | None) -> str:
    return (label or "").strip().lower().replace("-", "_").replace(" ", "_")


# --------------------------------------------------------------------------- #
# Twilio mapper
# --------------------------------------------------------------------------- #
#
# Twilio's ``AnsweredBy`` values (sync + async AMD):
#   human               -> a person answered
#   machine_start       -> machine greeting just started (beep not reached)
#   machine_end_beep    -> machine greeting finished at a beep
#   machine_end_silence -> machine greeting finished, no beep
#   machine_end_other   -> machine greeting finished (other)
#   fax                 -> fax machine
#   unknown             -> detection inconclusive / timed out
#
# All ``machine_*`` variants are voicemail for our purposes. ``fax`` is mapped
# to ``unknown`` (we have no fax handling) so the configurable fallback runs.

_TWILIO_ANSWERED_BY_MAP: Mapping[str, str] = {
    "human": AMD_HUMAN,
    "machine_start": AMD_VOICEMAIL,
    "machine_end_beep": AMD_VOICEMAIL,
    "machine_end_silence": AMD_VOICEMAIL,
    "machine_end_other": AMD_VOICEMAIL,
    "machine": AMD_VOICEMAIL,  # defensive: some flows emit bare "machine"
    "fax": AMD_UNKNOWN,
    "unknown": AMD_UNKNOWN,
}


def _twilio_mapper(label: str) -> str:
    return _TWILIO_ANSWERED_BY_MAP.get(label, AMD_UNKNOWN)


# --------------------------------------------------------------------------- #
# Provider registry
# --------------------------------------------------------------------------- #

_PROVIDERS: dict[str, ProviderMapper] = {
    "twilio": _twilio_mapper,
}


def register_provider(name: str, mapper: ProviderMapper) -> None:
    """Register (or override) a provider mapper.

    Lets new telephony/AMD providers plug into the canonical vocabulary
    without changing :func:`detect_answer_type` or any caller.
    """

    _PROVIDERS[name.strip().lower()] = mapper


def supported_providers() -> list[str]:
    return sorted(_PROVIDERS)


def detect_answer_type(
    answered_by: str | None,
    *,
    confidence: float | None = None,
    provider: str = "twilio",
) -> AMDResult:
    """Classify a provider answer label into a canonical :class:`AMDResult`.

    ``answered_by`` is the provider's raw label (e.g. Twilio ``AnsweredBy``).
    ``provider`` selects the mapper; unknown providers fall back to a pure
    canonical pass-through so a provider that already speaks our vocabulary
    (``human`` / ``voicemail`` / ``unknown``) works with no registration.
    """

    raw = _normalize(answered_by)
    mapper = _PROVIDERS.get((provider or "").strip().lower())

    if mapper is not None:
        result = mapper(raw)
    elif raw in CANONICAL_RESULTS:
        # Provider already emits canonical labels.
        result = raw
    else:
        result = AMD_UNKNOWN

    if result not in CANONICAL_RESULTS:
        result = AMD_UNKNOWN

    try:
        conf = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    return AMDResult(
        result=result,
        confidence=conf,
        raw=answered_by,
        provider=(provider or "unknown"),
    )
