"""Default playbook templates seeded per organization."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from modules.playbook.model import (
    PLAYBOOK_FRAMEWORK_BANT,
    PLAYBOOK_FRAMEWORK_MEDDICC,
    PLAYBOOK_STATUS_ACTIVE,
    Playbook,
    PlaybookField,
)
from modules.playbook.repository import PlaybookRepository

# Built-in BANT / MEDDICC field keys align with qualification.py cue dicts.
_BANT_FIELDS = [
    ("budget", "Budget", 2, True),
    ("authority", "Authority", 2, True),
    ("need", "Need", 2, True),
    ("timeline", "Timeline", 1, False),
]

_MEDDICC_FIELDS = [
    ("metrics", "Metrics", 2, True),
    ("economic_buyer", "Economic Buyer", 2, True),
    ("decision_criteria", "Decision Criteria", 1, False),
    ("decision_process", "Decision Process", 1, False),
    ("identify_pain", "Identify Pain", 2, True),
    ("champion", "Champion", 1, False),
    ("competition", "Competition", 1, False),
]

_DEFAULT_DISQUALIFIERS = [
    r"\b(remove me|do not call|do(?:n'?t)? call (me )?again|"
    r"not interested|stop calling|take me off|unsubscribe)\b",
]


def _make_fields(
    playbook_id: uuid.UUID,
    specs: list[tuple[str, str, int, bool]],
) -> list[PlaybookField]:
    return [
        PlaybookField(
            playbook_id=playbook_id,
            key=key,
            display_name=label,
            weight=weight,
            required=required,
            cue_patterns=[],
            position=i,
        )
        for i, (key, label, weight, required) in enumerate(specs)
    ]


def default_playbook_specs() -> list[dict]:
    """Return the three starter playbooks (not yet persisted)."""

    return [
        {
            "name": "Outbound SDR (BANT)",
            "description": "First-touch outbound call with BANT qualification.",
            "framework": PLAYBOOK_FRAMEWORK_BANT,
            "persona_name": "outbound_sdr",
            "default_objective": "book a 15-minute discovery call",
            "field_specs": _BANT_FIELDS,
        },
        {
            "name": "Appointment Setter",
            "description": "Schedule a meeting once intent is established.",
            "framework": PLAYBOOK_FRAMEWORK_BANT,
            "persona_name": "appointment_setter",
            "default_objective": "confirm a meeting in the next 7 days",
            "field_specs": _BANT_FIELDS,
        },
        {
            "name": "Support Triage",
            "description": "Inbound support intake and routing.",
            "framework": PLAYBOOK_FRAMEWORK_MEDDICC,
            "persona_name": "support_triage",
            "default_objective": "capture the issue and route to the right team",
            "field_specs": _MEDDICC_FIELDS,
        },
    ]


def seed_defaults_for_org(
    db: Session,
    *,
    organization_id: uuid.UUID,
    created_by: uuid.UUID | None = None,
) -> list[Playbook]:
    """Create starter playbooks if the org has none."""

    existing = PlaybookRepository.list_for_org(db, organization_id)
    if existing:
        return list(existing)

    created: list[Playbook] = []
    for spec in default_playbook_specs():
        pb = Playbook(
            organization_id=organization_id,
            created_by=created_by,
            name=spec["name"],
            description=spec["description"],
            status=PLAYBOOK_STATUS_ACTIVE,
            framework=spec["framework"],
            persona_name=spec["persona_name"],
            default_objective=spec["default_objective"],
            default_context={
                "company": "our company",
                "product": "our platform",
                "value_prop": "we help teams ship better outbound calls.",
            },
            disqualifying_patterns=_DEFAULT_DISQUALIFIERS,
            version=1,
        )
        PlaybookRepository.create(db, pb)
        PlaybookRepository.replace_fields(
            db,
            pb.id,
            _make_fields(pb.id, spec["field_specs"]),
        )
        created.append(pb)

    db.flush()
    return created
