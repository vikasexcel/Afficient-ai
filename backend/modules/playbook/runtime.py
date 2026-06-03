"""Runtime DTOs for resolving a playbook into call-time config."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlaybookFieldRuntime:
    key: str
    display_name: str
    description: str | None = None
    weight: int = 1
    required: bool = False
    cue_patterns: list[str] = field(default_factory=list)
    position: int = 0


@dataclass(frozen=True)
class PlaybookRuntimeConfig:
    """Resolved playbook used by prompts + qualification during a call."""

    playbook_id: uuid.UUID
    version: int
    name: str
    framework: str
    persona_name: str
    agent_name: str | None = None
    system_prompt: str | None = None
    opening_line: str | None = None
    default_objective: str | None = None
    voice_provider: str | None = None
    voice_id: str | None = None
    voice_name: str | None = None
    voice_gender: str | None = None
    voice_accent: str | None = None
    voice_language: str | None = None
    company_name: str | None = None
    company_intro: str | None = None
    company_description: str | None = None
    value_proposition: str | None = None
    default_context: dict[str, Any] | None = None
    disqualifying_patterns: list[str] = field(default_factory=list)
    fields: list[PlaybookFieldRuntime] = field(default_factory=list)
    branches: list[dict[str, Any]] = field(default_factory=list)
    objections: list[dict[str, Any]] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        """Serialise for Redis call meta (JSON-safe)."""

        return {
            "playbook_id": str(self.playbook_id),
            "playbook_version": self.version,
            "playbook_name": self.name,
            "framework": self.framework,
            "persona": self.persona_name,
            "agent_name": self.agent_name,
            "system_prompt": self.system_prompt,
            "opening_line": self.opening_line,
            "default_objective": self.default_objective,
            "voice_provider": self.voice_provider,
            "voice_id": self.voice_id,
            "voice_name": self.voice_name,
            "voice_gender": self.voice_gender,
            "voice_accent": self.voice_accent,
            "voice_language": self.voice_language,
            "company_name": self.company_name,
            "company_intro": self.company_intro,
            "company_description": self.company_description,
            "value_proposition": self.value_proposition,
            "default_context": self.default_context or {},
            "disqualifying_patterns": self.disqualifying_patterns,
            "playbook_branches": self.branches,
            "playbook_objections": self.objections,
            "fields": [
                {
                    "key": f.key,
                    "display_name": f.display_name,
                    "description": f.description,
                    "weight": f.weight,
                    "required": f.required,
                    "cue_patterns": f.cue_patterns,
                    "position": f.position,
                }
                for f in self.fields
            ],
        }

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> PlaybookRuntimeConfig | None:
        pid = meta.get("playbook_id")
        if not pid:
            return None
        fields_raw = meta.get("fields") or []
        fields = [
            PlaybookFieldRuntime(
                key=f["key"],
                display_name=f.get("display_name", f["key"]),
                description=f.get("description"),
                weight=int(f.get("weight", 1)),
                required=bool(f.get("required", False)),
                cue_patterns=list(f.get("cue_patterns") or []),
                position=int(f.get("position", 0)),
            )
            for f in fields_raw
        ]
        return cls(
            playbook_id=uuid.UUID(str(pid)),
            version=int(meta.get("playbook_version", 1)),
            name=str(meta.get("playbook_name", "")),
            framework=str(meta.get("framework", "BANT")),
            persona_name=str(meta.get("persona", "outbound_sdr")),
            agent_name=meta.get("agent_name"),
            system_prompt=meta.get("system_prompt"),
            opening_line=meta.get("opening_line"),
            default_objective=meta.get("default_objective"),
            voice_provider=meta.get("voice_provider"),
            voice_id=meta.get("voice_id"),
            voice_name=meta.get("voice_name"),
            voice_gender=meta.get("voice_gender"),
            voice_accent=meta.get("voice_accent"),
            voice_language=meta.get("voice_language"),
            company_name=meta.get("company_name"),
            company_intro=meta.get("company_intro"),
            company_description=meta.get("company_description"),
            value_proposition=meta.get("value_proposition"),
            default_context=meta.get("default_context"),
            disqualifying_patterns=list(meta.get("disqualifying_patterns") or []),
            branches=list(meta.get("playbook_branches") or []),
            objections=list(meta.get("playbook_objections") or []),
            fields=fields,
        )
