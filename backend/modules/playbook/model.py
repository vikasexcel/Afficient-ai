"""Persistence models for the playbook module.

Three tables:

* ``playbooks`` — the editable record. ``version`` increments every time
  the active playbook is published with changes; the ``status`` column
  tracks the lifecycle (``draft`` → ``active`` → ``archived``).
* ``playbook_versions`` — immutable snapshot of a playbook at a point in
  time. Written by :meth:`PlaybookService.publish`. Every call that uses
  the playbook records the version it ran against so historical analytics
  stay correct even after the live record is edited.
* ``playbook_fields`` — one row per qualification field. Edits replace
  the full set inside a transaction; we never partially mutate rows so
  the snapshot stored in ``playbook_versions.payload`` is always
  consistent with what was live at publish time.

Tenant scoping
--------------
``organization_id`` is part of every row. The service layer always
filters by tenant before touching anything; the router cross-checks
``tenant.organization_id`` against the loaded row for defence-in-depth.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    ARRAY,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import BaseModel


# Status vocabulary kept as plain strings so the column stays Alembic-
# friendly and easy to grep across logs.
PLAYBOOK_STATUS_DRAFT = "draft"
PLAYBOOK_STATUS_ACTIVE = "active"
PLAYBOOK_STATUS_ARCHIVED = "archived"

ALL_PLAYBOOK_STATUSES = frozenset(
    {
        PLAYBOOK_STATUS_DRAFT,
        PLAYBOOK_STATUS_ACTIVE,
        PLAYBOOK_STATUS_ARCHIVED,
    }
)

# Frameworks understood by the qualification tracker. ``CUSTOM`` means
# the field set on the playbook is fully user-defined and the tracker
# should ignore the built-in BANT / MEDDICC cue dictionaries.
PLAYBOOK_FRAMEWORK_BANT = "BANT"
PLAYBOOK_FRAMEWORK_MEDDICC = "MEDDICC"
PLAYBOOK_FRAMEWORK_CUSTOM = "CUSTOM"

ALL_PLAYBOOK_FRAMEWORKS = frozenset(
    {
        PLAYBOOK_FRAMEWORK_BANT,
        PLAYBOOK_FRAMEWORK_MEDDICC,
        PLAYBOOK_FRAMEWORK_CUSTOM,
    }
)


class Playbook(BaseModel):
    """Editable playbook record. The ``id`` is stable across versions."""

    __tablename__ = "playbooks"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(16), default=PLAYBOOK_STATUS_DRAFT, index=True
    )
    framework: Mapped[str] = mapped_column(
        String(16), default=PLAYBOOK_FRAMEWORK_BANT
    )

    # Persona drives the *base* system prompt template (looked up in
    # modules.ai.prompts._PERSONAS). ``system_prompt`` is an optional
    # override; when set it replaces the persona template wholesale.
    persona_name: Mapped[str] = mapped_column(
        String(64), default="outbound_sdr"
    )

    # Friendly name the AI uses to introduce itself on calls. Nullable for
    # backward compatibility; falls back to "AI Assistant" when unset.
    agent_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    opening_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_objective: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Per-playbook agent voice configuration. ``voice_id`` is the resolved
    # provider voice identifier passed to TTS at call time (an ElevenLabs
    # voice id today). The remaining columns are human-readable metadata so
    # the UI can render dropdowns without exposing raw ids, and so additional
    # providers (OpenAI TTS, Azure Speech, ...) can be supported later.
    voice_provider: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    voice_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    voice_gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    voice_accent: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    voice_language: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )

    # Company introduction — used in opening line + system prompt. Nullable for
    # backward compatibility with playbooks that only use ``default_context``.
    company_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    company_intro: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_proposition: Mapped[str | None] = mapped_column(Text, nullable=True)

    # {company, product, value_prop, ...} merged into render_system_prompt.
    default_context: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )

    # Disqualifying regex patterns evaluated *before* per-field cues.
    # Matching any pattern flips the qualification state to
    # ``disqualified`` and the orchestrator wraps the call up.
    disqualifying_patterns: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )

    # Declarative branch rules — see :mod:`modules.playbook.branches`.
    branches: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Objection handling rules — see :mod:`modules.playbook.objections`.
    # Nullable for backward compatibility (no rules == current GPT behaviour).
    objections: Mapped[list | None] = mapped_column(JSON, nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    fields: Mapped[list["PlaybookField"]] = relationship(
        "PlaybookField",
        back_populates="playbook",
        cascade="all, delete-orphan",
        order_by="PlaybookField.position",
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "name", name="uq_playbooks_org_name"
        ),
    )


class PlaybookField(BaseModel):
    """One qualification field belonging to a :class:`Playbook`."""

    __tablename__ = "playbook_fields"

    playbook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("playbooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ``key`` is the machine-friendly identifier (e.g. ``budget``,
    # ``metrics``). ``display_name`` is what shows up in the UI.
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    # Higher weight contributes more to the qualification score.
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=False)

    # Regex patterns the QualificationTracker matches against each user
    # turn. Empty list falls back to the framework default cue
    # dictionary (BANT / MEDDICC) for the matching ``key``.
    cue_patterns: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )

    # Ordering hint for the UI / system-prompt rendering.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    playbook: Mapped["Playbook"] = relationship(
        "Playbook", back_populates="fields"
    )

    __table_args__ = (
        UniqueConstraint(
            "playbook_id", "key", name="uq_playbook_field_key"
        ),
    )


class PlaybookVersion(BaseModel):
    """Immutable snapshot of a playbook at the time it was published.

    ``payload`` carries the entire serialised playbook (record + fields)
    so reconstructing the state used by a historical call requires no
    joins. We also store the ``Playbook.id`` separately so listing is
    cheap.
    """

    __tablename__ = "playbook_versions"

    playbook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("playbooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "playbook_id", "version", name="uq_playbook_version"
        ),
    )


# Composite index for the common "list playbooks for an org" query
# ordered by recency.
Index(
    "ix_playbooks_org_updated",
    Playbook.organization_id,
    Playbook.updated_at,
)
