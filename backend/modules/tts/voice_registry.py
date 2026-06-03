"""Configurable voice registry.

Maps human-readable voice names to provider voice ids so the UI can offer
friendly dropdowns (Gender → Accent → Voice) without users ever needing to
know a raw ElevenLabs voice id.

Design goals
------------
* **Future-proof providers.** ``VoiceProvider`` is an open vocabulary. Today
  only ElevenLabs is wired end-to-end, but the registry shape (and the
  ``provider`` field on every voice) lets OpenAI TTS / Azure Speech / custom
  providers be added later without schema changes.
* **Configurable, not hardcoded in the UI.** The frontend fetches this
  registry from ``GET /api/v1/tts/voice-registry`` — voice ids never live in
  the client bundle. Operators can also override the curated defaults via the
  ``TTS_VOICE_REGISTRY_JSON`` env var (a JSON list of voice dicts) to add,
  remove, or correct entries without a code change.
* **Live catalog still works.** The same endpoint can merge ElevenLabs' live
  ``/voices`` list for advanced users; the curated registry is the reliable
  baseline.

The curated ElevenLabs ids below are the well-known public/premade voices.
Because ElevenLabs occasionally reuses ids across its default library, treat
these as sensible defaults that operators can override via the env var above
or that advanced users can bypass with a custom Voice ID on the playbook.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from common.logging import get_logger
from config.settings import settings

log = get_logger("tts.voice_registry")


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

VOICE_PROVIDER_ELEVENLABS = "elevenlabs"
VOICE_PROVIDER_OPENAI = "openai"
VOICE_PROVIDER_AZURE = "azure"
VOICE_PROVIDER_CUSTOM = "custom"

# Providers the system *accepts* on a playbook. Only ElevenLabs is fully
# wired into the live call path today; the rest are reserved so the field and
# UI can grow without a migration.
SUPPORTED_VOICE_PROVIDERS = frozenset(
    {
        VOICE_PROVIDER_ELEVENLABS,
        VOICE_PROVIDER_OPENAI,
        VOICE_PROVIDER_AZURE,
        VOICE_PROVIDER_CUSTOM,
    }
)

# Providers whose voices we can actually synthesize right now.
ENABLED_VOICE_PROVIDERS = frozenset({VOICE_PROVIDER_ELEVENLABS})

DEFAULT_VOICE_PROVIDER = VOICE_PROVIDER_ELEVENLABS

GENDER_MALE = "male"
GENDER_FEMALE = "female"
ALL_GENDERS = frozenset({GENDER_MALE, GENDER_FEMALE})

# Accent vocabulary surfaced in the UI dropdown. Intentionally limited to
# US and UK to keep voice selection simple and professional.
ACCENT_US = "US"
ACCENT_UK = "UK"
ALL_ACCENTS = (
    ACCENT_US,
    ACCENT_UK,
)


@dataclass(frozen=True)
class RegistryVoice:
    """A curated, human-friendly voice entry."""

    provider: str
    voice_id: str
    name: str
    gender: str
    accent: str
    language: str = "en"
    description: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "provider": self.provider,
            "voice_id": self.voice_id,
            "name": self.name,
            "gender": self.gender,
            "accent": self.accent,
            "language": self.language,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Curated default registry
# ---------------------------------------------------------------------------
#
# These are the friendly voices offered out of the box. Operators can extend
# or override this set via ``TTS_VOICE_REGISTRY_JSON`` (see ``_load_overrides``).

_DEFAULT_ELEVENLABS_VOICES: tuple[RegistryVoice, ...] = (
    # --- Female ---
    # Verified voice ids from the connected ElevenLabs account. Accents
    # default to US; adjust here (or via TTS_VOICE_REGISTRY_JSON) if a voice
    # is actually UK/Australian/etc.
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="lcMyyd2HUfFzxdCaC4Ta",
        name="Rachel",
        gender=GENDER_FEMALE,
        accent=ACCENT_US,
        description="Warm, natural female voice.",
    ),
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="exsUS4vynmxd379XN4yO",
        name="Bella",
        gender=GENDER_FEMALE,
        accent=ACCENT_US,
        description="Soft, friendly female voice.",
    ),
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="QrjqRcZWGRzghe6ZPmh2",
        name="Sarah",
        gender=GENDER_FEMALE,
        accent=ACCENT_US,
        description="Clear, professional female voice.",
    ),
    # --- Male ---
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="XZEfcFyBnzsNJrdvkWdI",
        name="Adam",
        gender=GENDER_MALE,
        accent=ACCENT_US,
        description="Deep, steady male voice.",
    ),
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="Iwr5uai9ZpKy4XMRJc3w",
        name="Josh",
        gender=GENDER_MALE,
        accent=ACCENT_US,
        description="Young, natural male voice.",
    ),
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="j57KDF72L6gxbLk4sOo5",
        name="Daniel",
        gender=GENDER_MALE,
        accent=ACCENT_US,
        description="Confident, articulate male voice.",
    ),
    # --- UK Female ---
    # Public ElevenLabs library voice ids as sensible defaults. Operators
    # should override these with their own account voice ids via
    # ``TTS_VOICE_REGISTRY_JSON`` if they differ.
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="XB0fDUnXU5powFXDhCwa",
        name="Charlotte",
        gender=GENDER_FEMALE,
        accent=ACCENT_UK,
        description="Warm British female voice.",
    ),
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="Xb7hH8MSUJpSbSDYk0k2",
        name="Sophie",
        gender=GENDER_FEMALE,
        accent=ACCENT_UK,
        description="Clear British female voice.",
    ),
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="pFZP5JQG7iQjIQuC4Bku",
        name="Emma",
        gender=GENDER_FEMALE,
        accent=ACCENT_UK,
        description="Friendly British female voice.",
    ),
    # --- UK Male ---
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="JBFqnCBsd6RMkjVDRZzb",
        name="George",
        gender=GENDER_MALE,
        accent=ACCENT_UK,
        description="Mature British male voice.",
    ),
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="SOYHLrjzK2X1ezoPC6cr",
        name="Arthur",
        gender=GENDER_MALE,
        accent=ACCENT_UK,
        description="Refined British male voice.",
    ),
    RegistryVoice(
        provider=VOICE_PROVIDER_ELEVENLABS,
        voice_id="N2lVS1w4EtoT3dr4eOWO",
        name="Callum",
        gender=GENDER_MALE,
        accent=ACCENT_UK,
        description="Confident British male voice.",
    ),
)


def _load_overrides() -> tuple[RegistryVoice, ...]:
    """Parse ``TTS_VOICE_REGISTRY_JSON`` into extra/override voices.

    The env var (when set) is a JSON array of objects with at least
    ``voice_id``, ``name``, ``gender`` and ``accent``. ``provider`` defaults
    to ElevenLabs and ``language`` to ``en``. Entries with the same
    ``(provider, voice_id)`` as a default replace it.
    """

    raw = getattr(settings, "TTS_VOICE_REGISTRY_JSON", "") or ""
    raw = raw.strip()
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("tts.voice_registry.bad_override_json")
        return ()
    if not isinstance(data, list):
        log.warning("tts.voice_registry.override_not_list")
        return ()

    out: list[RegistryVoice] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                RegistryVoice(
                    provider=str(
                        item.get("provider") or DEFAULT_VOICE_PROVIDER
                    ).lower(),
                    voice_id=str(item["voice_id"]),
                    name=str(item["name"]),
                    gender=str(item["gender"]).lower(),
                    accent=str(item["accent"]),
                    language=str(item.get("language") or "en"),
                    description=item.get("description"),
                )
            )
        except (KeyError, TypeError):
            log.warning("tts.voice_registry.bad_override_entry", entry=item)
            continue
    return tuple(out)


def _build_registry() -> tuple[RegistryVoice, ...]:
    overrides = _load_overrides()
    by_key: dict[tuple[str, str], RegistryVoice] = {}
    for v in _DEFAULT_ELEVENLABS_VOICES:
        by_key[(v.provider, v.voice_id)] = v
    for v in overrides:
        by_key[(v.provider, v.voice_id)] = v
    return tuple(by_key.values())


# Built once at import; the override env var is read at process start which
# matches how the rest of ``settings`` behaves.
_REGISTRY: tuple[RegistryVoice, ...] = _build_registry()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_voices(
    *,
    provider: str | None = None,
    gender: str | None = None,
    accent: str | None = None,
) -> list[RegistryVoice]:
    """Return curated voices, optionally filtered by provider/gender/accent."""

    out = list(_REGISTRY)
    if provider:
        out = [v for v in out if v.provider == provider.lower()]
    if gender:
        out = [v for v in out if v.gender == gender.lower()]
    if accent:
        out = [v for v in out if v.accent == accent]
    return out


def get_voice(provider: str, voice_id: str) -> RegistryVoice | None:
    """Look up a curated voice by provider + id (``None`` if not curated)."""

    provider = (provider or DEFAULT_VOICE_PROVIDER).lower()
    for v in _REGISTRY:
        if v.provider == provider and v.voice_id == voice_id:
            return v
    return None


def is_supported_provider(provider: str | None) -> bool:
    return bool(provider) and provider.lower() in SUPPORTED_VOICE_PROVIDERS


def is_enabled_provider(provider: str | None) -> bool:
    return bool(provider) and provider.lower() in ENABLED_VOICE_PROVIDERS


def provider_catalog() -> list[dict[str, object]]:
    """Describe known providers for the UI (enabled = synthesizable today)."""

    labels = {
        VOICE_PROVIDER_ELEVENLABS: "ElevenLabs",
        VOICE_PROVIDER_OPENAI: "OpenAI TTS",
        VOICE_PROVIDER_AZURE: "Azure Speech",
        VOICE_PROVIDER_CUSTOM: "Custom Provider",
    }
    order = (
        VOICE_PROVIDER_ELEVENLABS,
        VOICE_PROVIDER_OPENAI,
        VOICE_PROVIDER_AZURE,
        VOICE_PROVIDER_CUSTOM,
    )
    return [
        {
            "id": p,
            "label": labels[p],
            "enabled": p in ENABLED_VOICE_PROVIDERS,
        }
        for p in order
    ]
