"""Company introduction fields for playbooks — prompt + opening line helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.playbook.exceptions import PlaybookValidationError
from modules.playbook.runtime import PlaybookRuntimeConfig


# Backward-compatible fallback used when a playbook has no ``agent_name``.
DEFAULT_AGENT_NAME = "AI Assistant"


def resolve_agent_name(runtime: PlaybookRuntimeConfig) -> str:
    """Agent's spoken name with backward-compatible fallback.

    Prefers ``runtime.agent_name``, then a legacy ``default_context`` value,
    then :data:`DEFAULT_AGENT_NAME`.
    """

    dc = runtime.default_context or {}
    name = runtime.agent_name or dc.get("agent_name")
    return _str_or_none(name) or DEFAULT_AGENT_NAME


@dataclass(frozen=True)
class CompanyProfile:
    """Resolved company copy for a call (columns + legacy ``default_context``)."""

    company_name: str | None = None
    company_intro: str | None = None
    company_description: str | None = None
    value_proposition: str | None = None

    @property
    def has_any(self) -> bool:
        return bool(
            (self.company_name or "").strip()
            or (self.company_intro or "").strip()
            or (self.company_description or "").strip()
            or (self.value_proposition or "").strip()
        )


def _merge_company_profile(
    *,
    company_name: str | None,
    company_intro: str | None,
    company_description: str | None,
    value_proposition: str | None,
    default_context: dict | None,
) -> CompanyProfile:
    dc = default_context or {}
    name = company_name or dc.get("company") or dc.get("company_name")
    intro = company_intro or dc.get("company_intro")
    description = (
        company_description
        or dc.get("company_description")
        or dc.get("product")
    )
    value_prop = (
        value_proposition or dc.get("value_prop") or dc.get("value_proposition")
    )
    return CompanyProfile(
        company_name=_str_or_none(name),
        company_intro=_str_or_none(intro),
        company_description=_str_or_none(description),
        value_proposition=_str_or_none(value_prop),
    )


def resolve_company_profile(runtime: PlaybookRuntimeConfig) -> CompanyProfile:
    """Merge dedicated columns with legacy ``default_context`` keys."""

    return _merge_company_profile(
        company_name=runtime.company_name,
        company_intro=runtime.company_intro,
        company_description=runtime.company_description,
        value_proposition=runtime.value_proposition,
        default_context=runtime.default_context,
    )


def _dedicated_company_columns_set(pb: Any) -> bool:
    return bool(
        _str_or_none(pb.company_name)
        or _str_or_none(pb.company_intro)
        or _str_or_none(pb.company_description)
        or _str_or_none(pb.value_proposition)
    )


def validate_company_fields(pb: Any) -> None:
    """Validate company columns when any dedicated field is in use.

    Legacy playbooks with only ``default_context`` company keys are not
    forced to migrate. When any dedicated column is set, name and intro are
    required.
    """

    if not _dedicated_company_columns_set(pb):
        return

    profile = _merge_company_profile(
        company_name=pb.company_name,
        company_intro=pb.company_intro,
        company_description=pb.company_description,
        value_proposition=pb.value_proposition,
        default_context=pb.default_context,
    )

    if not profile.company_name:
        raise PlaybookValidationError(
            "Company Name is required when company fields are configured",
            status_code=400,
        )
    if not profile.company_intro:
        raise PlaybookValidationError(
            "Company Introduction is required when company fields are configured",
            status_code=400,
        )


def apply_company_to_prompt_context(
    ctx: dict[str, Any],
    profile: CompanyProfile,
) -> None:
    """Map company fields onto persona template placeholders."""

    if profile.company_name:
        ctx["company"] = profile.company_name
        ctx["company_name"] = profile.company_name
    if profile.company_intro:
        ctx["company_intro"] = profile.company_intro
    if profile.company_description:
        ctx["product"] = profile.company_description
        ctx["company_description"] = profile.company_description
    if profile.value_proposition:
        ctx["value_prop"] = profile.value_proposition
        ctx["value_proposition"] = profile.value_proposition


def company_prompt_block(profile: CompanyProfile) -> str:
    """Extra system-prompt section with structured company copy."""

    if not profile.has_any:
        return ""

    parts: list[str] = ["Company context (use when explaining who you represent):"]
    if profile.company_name:
        parts.append(f"Company Name: {profile.company_name}")
    if profile.company_intro:
        parts.append(f"Company Introduction:\n{profile.company_intro}")
    if profile.company_description:
        parts.append(f"Company Description:\n{profile.company_description}")
    if profile.value_proposition:
        parts.append(f"Value Proposition:\n{profile.value_proposition}")
    parts.append(
        "Introduce yourself as from the company name above. Weave the introduction, "
        "description, and value proposition naturally when the prospect asks what you do "
        "or why you are calling."
    )
    return "\n\n".join(parts)


def resolve_opening_line(
    runtime: PlaybookRuntimeConfig,
    *,
    agent_name: str,
) -> str | None:
    """Opening utterance for TTS — custom line or auto-generated from company fields.

    When ``opening_line`` is set, ``{agent_name}`` and ``{company_name}`` placeholders
    are expanded. When empty but ``company_name`` is configured, builds:

    ``Hi, this is {agent} from {company}. {company_intro}``
    """

    profile = resolve_company_profile(runtime)
    company = profile.company_name or ""

    if runtime.opening_line and runtime.opening_line.strip():
        return _expand_opening_placeholders(
            runtime.opening_line.strip(),
            agent_name=agent_name,
            company_name=company,
        )

    # Auto-generate only when there's a configured identity to introduce.
    # Legacy playbooks with neither an agent name nor company keep their
    # previous (possibly empty) opening behaviour.
    has_identity = bool(runtime.agent_name) or bool(company)
    if not has_identity:
        return runtime.opening_line

    if company:
        line = f"Hi, this is {agent_name} from {company}."
        if profile.company_intro:
            line = f"{line} {profile.company_intro.strip()}"
    else:
        line = f"Hi, this is {agent_name}."
    return line


def _expand_opening_placeholders(
    text: str,
    *,
    agent_name: str,
    company_name: str,
) -> str:
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return ""

    return text.format_map(
        _Safe(
            agent_name=agent_name,
            company_name=company_name or "our team",
            company=company_name or "our company",
        )
    )


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None
