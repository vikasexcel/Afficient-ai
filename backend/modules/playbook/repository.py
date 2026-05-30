"""Data-access layer for playbooks."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.orm import Session, joinedload

from modules.playbook.model import (
    PLAYBOOK_STATUS_ACTIVE,
    PLAYBOOK_STATUS_ARCHIVED,
    PLAYBOOK_STATUS_DRAFT,
    Playbook,
    PlaybookField,
    PlaybookVersion,
)


class PlaybookRepository:
    @staticmethod
    def create(db: Session, playbook: Playbook) -> Playbook:
        db.add(playbook)
        db.flush()
        return playbook

    @staticmethod
    def get(
        db: Session,
        playbook_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None = None,
        with_fields: bool = True,
    ) -> Playbook | None:
        q = db.query(Playbook).filter(Playbook.id == playbook_id)
        if organization_id is not None:
            q = q.filter(Playbook.organization_id == organization_id)
        if with_fields:
            q = q.options(joinedload(Playbook.fields))  # type: ignore[attr-defined]
        return q.one_or_none()

    @staticmethod
    def get_by_name(
        db: Session,
        *,
        organization_id: uuid.UUID,
        name: str,
    ) -> Playbook | None:
        return (
            db.query(Playbook)
            .filter(
                Playbook.organization_id == organization_id,
                Playbook.name == name,
            )
            .one_or_none()
        )

    @staticmethod
    def list_for_org(
        db: Session,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        include_archived: bool = False,
    ) -> Sequence[Playbook]:
        q = db.query(Playbook).filter(
            Playbook.organization_id == organization_id
        )
        if status is not None:
            q = q.filter(Playbook.status == status)
        elif not include_archived:
            q = q.filter(Playbook.status != PLAYBOOK_STATUS_ARCHIVED)
        return q.order_by(Playbook.updated_at.desc()).all()

    @staticmethod
    def replace_fields(
        db: Session,
        playbook_id: uuid.UUID,
        fields: list[PlaybookField],
    ) -> list[PlaybookField]:
        db.query(PlaybookField).filter(
            PlaybookField.playbook_id == playbook_id
        ).delete(synchronize_session=False)
        for f in fields:
            db.add(f)
        db.flush()
        return fields

    @staticmethod
    def count_fields(db: Session, playbook_id: uuid.UUID) -> int:
        return (
            db.query(PlaybookField)
            .filter(PlaybookField.playbook_id == playbook_id)
            .count()
        )


class PlaybookVersionRepository:
    @staticmethod
    def create(db: Session, version: PlaybookVersion) -> PlaybookVersion:
        db.add(version)
        db.flush()
        return version

    @staticmethod
    def list_for_playbook(
        db: Session,
        playbook_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None = None,
    ) -> Sequence[PlaybookVersion]:
        q = db.query(PlaybookVersion).filter(
            PlaybookVersion.playbook_id == playbook_id
        )
        if organization_id is not None:
            q = q.filter(PlaybookVersion.organization_id == organization_id)
        return q.order_by(PlaybookVersion.version.desc()).all()

    @staticmethod
    def get_version(
        db: Session,
        playbook_id: uuid.UUID,
        version: int,
    ) -> PlaybookVersion | None:
        return (
            db.query(PlaybookVersion)
            .filter(
                PlaybookVersion.playbook_id == playbook_id,
                PlaybookVersion.version == version,
            )
            .one_or_none()
        )
