"""Apply a resolved playbook to an outbound / live call."""

from __future__ import annotations

from typing import Any

from modules.ai.prompts import get_persona
from modules.playbook.company import (
    apply_company_to_prompt_context,
    resolve_agent_name,
    resolve_company_profile,
)
from modules.playbook.objections import objection_summary, parse_objections
from modules.playbook.runtime import PlaybookRuntimeConfig


def build_call_extra_context(
    runtime: PlaybookRuntimeConfig,
    *,
    lead_name: str | None = None,
    lead_phone: str | None = None,
    caller_extra: dict[str, Any] | None = None,
    playbook_controls_call: bool = True,
) -> dict[str, Any]:
    """Build ``extra_context`` for the orchestrator / Redis meta.

    When ``playbook_controls_call`` is true (phone dialer with a playbook),
    only lead identity fields from ``caller_extra`` are merged on top of the
    playbook — conversation knobs must not override the playbook.
    """

    persona = get_persona(runtime.persona_name)
    ctx: dict[str, Any] = dict(runtime.default_context or {})
    apply_company_to_prompt_context(ctx, resolve_company_profile(runtime))

    if runtime.default_objective:
        ctx.setdefault("objective", runtime.default_objective)
    elif persona.default_objective:
        ctx.setdefault("objective", persona.default_objective)

    # Friendly spoken name for {agent_name} in persona templates. The
    # playbook's configured agent name wins; falls back to "AI Assistant".
    ctx["agent_name"] = resolve_agent_name(runtime)

    if lead_name:
        ctx["lead_name"] = lead_name
    if lead_phone:
        ctx["lead_phone"] = lead_phone

    if caller_extra:
        if playbook_controls_call:
            for key in ("lead_name", "lead_phone", "lead_email", "timezone"):
                if key in caller_extra and caller_extra[key]:
                    ctx[key] = caller_extra[key]
        else:
            ctx.update(caller_extra)

    return ctx


def _persona_agent_name(persona_name: str) -> str:
    """Human label used in system prompts as ``{agent_name}``."""

    labels = {
        "outbound_sdr": "Alex",
        "appointment_setter": "Sam",
        "support_triage": "Support Agent",
    }
    if persona_name in labels:
        return labels[persona_name]
    return persona_name.replace("_", " ").title()


def playbook_application_summary(runtime: PlaybookRuntimeConfig) -> dict[str, Any]:
    """Compact payload for structured logs."""

    return {
        "playbook_id": str(runtime.playbook_id),
        "playbook_name": runtime.name,
        "playbook_version": runtime.version,
        "persona": runtime.persona_name,
        "framework": runtime.framework,
        "voice_id": runtime.voice_id,
        "voice_name": runtime.voice_name,
        "voice_provider": runtime.voice_provider or "elevenlabs",
        "field_count": len(runtime.fields),
        "branch_count": len(runtime.branches),
        **objection_summary(parse_objections(runtime.objections)),
        "has_system_prompt": bool(runtime.system_prompt),
        "has_opening_line": bool(runtime.opening_line),
        "company_name": resolve_company_profile(runtime).company_name,
        "agent_name": resolve_agent_name(runtime),
    }
