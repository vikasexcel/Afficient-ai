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
    system_prompt: str | None = None
    opening_line: str | None = None
    default_objective: str | None = None
    voice_id: str | None = None
    default_context: dict[str, Any] | None = None
    disqualifying_patterns: list[str] = field(default_factory=list)
    fields: list[PlaybookFieldRuntime] = field(default_factory=list)
    branches: list[dict[str, Any]] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        """Serialise for Redis call meta (JSON-safe)."""

        return {
            "playbook_id": str(self.playbook_id),
            "playbook_version": self.version,
            "playbook_name": self.name,
            "framework": self.framework,
            "persona": self.persona_name,
            "opening_line": self.opening_line,
            "default_objective": self.default_objective,
            "voice_id": self.voice_id,
            "default_context": self.default_context or {},
            "disqualifying_patterns": self.disqualifying_patterns,
            "playbook_branches": self.branches,
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
            system_prompt=meta.get("system_prompt"),
            opening_line=meta.get("opening_line"),
            default_objective=meta.get("default_objective"),
            voice_id=meta.get("voice_id"),
            default_context=meta.get("default_context"),
            disqualifying_patterns=list(meta.get("disqualifying_patterns") or []),
            branches=list(meta.get("playbook_branches") or []),
            fields=fields,
        )
