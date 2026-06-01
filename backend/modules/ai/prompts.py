"""System prompt management.

Two responsibilities:

* Hold reusable persona prompts (outbound SDR, qualification specialist,
  appointment setter, ...). New personas can be registered at runtime
  via :func:`register_persona`.
* Render a final system prompt that combines the persona, the chosen
  qualification framework (BANT / MEDDICC), and arbitrary per-call
  context (lead name, company, objective, ...).

Keep prompts short and explicit. The agent is on a phone call: long
system prompts add prompt-tokens which inflate latency and cost on every
turn. Aim for < 800 tokens of system instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from modules.ai.qualification import QualificationFramework

if TYPE_CHECKING:
    from modules.playbook.runtime import PlaybookRuntimeConfig


# ---------------------------------------------------------------------------
# Persona registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Persona:
    """A named system prompt template.

    ``template`` may reference ``{lead_name}``, ``{company}``, ``{product}``,
    ``{objective}``, ``{value_prop}``, ``{qualification_block}`` and any
    other key passed via ``extra_context``. Missing keys render as empty
    strings rather than raising — we never want a single missing field
    to fail a live call.
    """

    name: str
    description: str
    template: str
    default_objective: str = ""


_OUTBOUND_SDR = Persona(
    name="outbound_sdr",
    description=(
        "Friendly outbound SDR placing the first call. Goals: confirm the "
        "person, deliver a one-sentence value prop, qualify the lead, and "
        "either book a follow-up meeting or politely close the call."
    ),
    default_objective="book a 15-minute discovery call",
    template=(
        "You are {agent_name}, an outbound sales development representative "
        "for {company}. You are on a live phone call with {lead_name}. "
        "Your objective: {objective}.\n"
        "\n"
        "Style rules:\n"
        "- Speak naturally and concisely (1–2 short sentences per turn).\n"
        "- Never read URLs, code, lists, or markdown — this is a voice call.\n"
        "- Greet warmly, confirm you have the right person, then state the value prop in one line.\n"
        "- Acknowledge objections before answering. Mirror their words once if useful.\n"
        "- If the lead asks for time, offer two concrete slots in their timezone.\n"
        "- If the lead asks to be removed, confirm and end the call politely.\n"
        "- If unsure, ask one clarifying question rather than guess.\n"
        "\n"
        "Product context: {product}\n"
        "Value proposition: {value_prop}\n"
        "\n"
        "{qualification_block}\n"
        "\n"
        "Remember: every reply is spoken aloud immediately. Keep it short, "
        "human, and forward-moving."
    ),
)


_APPOINTMENT_SETTER = Persona(
    name="appointment_setter",
    description=(
        "Specialised on scheduling a meeting once the lead has shown intent. "
        "Skip discovery; focus on offering and confirming a slot."
    ),
    default_objective="confirm a meeting in the next 7 days",
    template=(
        "You are {agent_name}, scheduling assistant for {company}. {lead_name} "
        "has expressed interest in a follow-up.\n"
        "\n"
        "Objective: {objective}.\n"
        "\n"
        "Style rules:\n"
        "- Suggest two specific slots and ask which works.\n"
        "- Confirm timezone explicitly the first time.\n"
        "- Once a slot is agreed, repeat it back verbatim for confirmation.\n"
        "- Keep replies under two sentences.\n"
        "\n"
        "{qualification_block}"
    ),
)


_SUPPORT_TRIAGE = Persona(
    name="support_triage",
    description=(
        "Inbound support call. Gather symptom, urgency, account id; route "
        "or escalate. Never invent solutions."
    ),
    default_objective="capture the issue and route to the right team",
    template=(
        "You are {agent_name}, support intake for {company}. The caller "
        "({lead_name}) has reached out for help.\n"
        "\n"
        "Objective: {objective}.\n"
        "\n"
        "Style rules:\n"
        "- Express empathy briefly, then ask one focused question at a time.\n"
        "- Collect: account/email, exact symptom, when it started, blast radius.\n"
        "- If the user is in distress, slow down and reassure.\n"
        "- Never promise a fix; confirm next steps and ETA only.\n"
        "\n"
        "{qualification_block}"
    ),
)


_PERSONAS: dict[str, Persona] = {
    p.name: p
    for p in (_OUTBOUND_SDR, _APPOINTMENT_SETTER, _SUPPORT_TRIAGE)
}


def register_persona(persona: Persona) -> None:
    """Add or override a persona at runtime (used by tests and tenant config)."""

    _PERSONAS[persona.name] = persona


def get_persona(name: str | None) -> Persona:
    """Look up a persona, falling back to ``outbound_sdr`` when missing."""

    if not name:
        return _OUTBOUND_SDR
    return _PERSONAS.get(name, _OUTBOUND_SDR)


def list_personas() -> list[Persona]:
    return list(_PERSONAS.values())


# ---------------------------------------------------------------------------
# Qualification block rendering
# ---------------------------------------------------------------------------


_BANT_BLOCK = (
    "Qualification framework: BANT.\n"
    "On every turn, silently update your understanding of:\n"
    "  - Budget: do they have or control budget for this?\n"
    "  - Authority: are they the decision maker or influencer?\n"
    "  - Need: what concrete problem are they trying to solve?\n"
    "  - Timeline: when do they need a solution in place?\n"
    "Ask at most one qualifying question per turn, woven into the conversation."
)


_MEDDICC_BLOCK = (
    "Qualification framework: MEDDICC.\n"
    "Track silently across the conversation:\n"
    "  - Metrics: quantifiable pain or KPI they care about.\n"
    "  - Economic buyer: who signs the cheque?\n"
    "  - Decision criteria: what they will evaluate on.\n"
    "  - Decision process: who/when/how they decide.\n"
    "  - Identify pain: the explicit business pain.\n"
    "  - Champion: an internal advocate.\n"
    "  - Competition: what alternatives they are evaluating.\n"
    "Probe one MEDDICC dimension per turn, never interrogate."
)


def _qualification_block(
    framework: QualificationFramework | str | None,
    playbook: PlaybookRuntimeConfig | None = None,
) -> str:
    if playbook and playbook.fields:
        lines = [
            f"Qualification playbook: {playbook.name} ({playbook.framework}).",
            "On every turn, silently update your understanding of:",
        ]
        for f in sorted(playbook.fields, key=lambda x: x.position):
            req = " (required)" if f.required else ""
            desc = f" — {f.description}" if f.description else ""
            lines.append(
                f"  - {f.display_name} [{f.key}]{req}{desc}"
            )
        lines.append(
            "Ask at most one qualifying question per turn, woven into the conversation."
        )
        return "\n".join(lines)

    if framework is None:
        return ""
    fw = (
        framework
        if isinstance(framework, QualificationFramework)
        else QualificationFramework(framework)
    )
    if fw == QualificationFramework.BANT:
        return _BANT_BLOCK
    if fw == QualificationFramework.MEDDICC:
        return _MEDDICC_BLOCK
    return ""


# ---------------------------------------------------------------------------
# Final render
# ---------------------------------------------------------------------------


_DEFAULT_CONTEXT: dict[str, str] = {
    "agent_name": "Aifficient Agent",
    "company": "our company",
    # When the lead's name is unknown, we want the rendered prompt to
    # read naturally ("on a live phone call with the prospect" rather
    # than the previous "with there"). The greeting fallback ("hi
    # there") is still safe because the persona templates phrase it
    # explicitly.
    "lead_name": "the prospect",
    "product": "our platform",
    "value_prop": "we help teams ship better outbound calls.",
    "objective": "",
}


def render_system_prompt(
    *,
    persona: str | Persona | None = None,
    framework: QualificationFramework | str | None = None,
    extra_context: dict[str, Any] | None = None,
    playbook: PlaybookRuntimeConfig | None = None,
) -> str:
    """Render the final system prompt for a turn.

    Missing template keys render as empty strings — this is intentional so
    a misconfigured campaign can't crash a live call.

    When ``playbook.system_prompt`` is set it replaces the persona template
    entirely; otherwise the persona template is used.
    """

    if playbook is not None:
        persona = playbook.persona_name
        framework = playbook.framework

    p = persona if isinstance(persona, Persona) else get_persona(persona)

    ctx: dict[str, Any] = {**_DEFAULT_CONTEXT}
    if playbook and playbook.default_objective:
        ctx["objective"] = playbook.default_objective
    elif p.default_objective:
        ctx["objective"] = p.default_objective
    if playbook and playbook.default_context:
        ctx.update(
            {
                k: ("" if v is None else str(v))
                for k, v in playbook.default_context.items()
            }
        )
    if extra_context:
        ctx.update({k: ("" if v is None else str(v)) for k, v in extra_context.items()})

    ctx["qualification_block"] = _qualification_block(framework, playbook)

    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:  # noqa: D401 - intentional
            return ""

    template = (
        playbook.system_prompt
        if playbook and playbook.system_prompt
        else p.template
    )
    rendered = template.format_map(_SafeDict(ctx)).strip()
    dynamic = (extra_context or {}).get("dynamic_block") if extra_context else None
    if dynamic:
        rendered = f"{rendered}\n\n{str(dynamic).strip()}"
    return rendered.strip()
