"""Playbook business logic — CRUD, publish, versioning, dry-run."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from common.logging import get_logger
from modules.ai.prompts import render_system_prompt
from modules.ai.qualification import (
    QualificationFramework,
    QualificationState,
    QualificationTracker,
)
from modules.playbook.exceptions import (
    PlaybookConflictError,
    PlaybookNotFoundError,
    PlaybookValidationError,
)
from modules.playbook.model import (
    PLAYBOOK_FRAMEWORK_BANT,
    PLAYBOOK_FRAMEWORK_CUSTOM,
    PLAYBOOK_FRAMEWORK_MEDDICC,
    PLAYBOOK_STATUS_ACTIVE,
    PLAYBOOK_STATUS_ARCHIVED,
    PLAYBOOK_STATUS_DRAFT,
    Playbook,
    PlaybookField,
    PlaybookVersion,
)
from modules.playbook.repository import (
    PlaybookRepository,
    PlaybookVersionRepository,
)
from modules.playbook.branches import evaluate_branches, parse_branch_rules
from modules.playbook.company import validate_company_fields
from modules.playbook.objections import (
    match_objection,
    objection_turn_instruction,
    parse_objections,
)
from modules.playbook.runtime import PlaybookFieldRuntime, PlaybookRuntimeConfig
from modules.playbook.schema import (
    CreatePlaybookInput,
    PlaybookDetail,
    PlaybookFieldInput,
    PlaybookFieldOut,
    PlaybookPromptPreview,
    PlaybookSummary,
    PlaybookTestInput,
    PlaybookTestResponse,
    PlaybookVersionOut,
    ObjectionMatchOut,
    UpdatePlaybookInput,
)

log = get_logger("playbook.service")


def _log_voice_selected(pb: Playbook, *, action: str) -> None:
    """Emit ``VOICE_SELECTED`` when a playbook has a voice configured."""

    if not pb.voice_id:
        return
    log.info(
        "playbook.VOICE_SELECTED",
        action=action,
        playbook_id=str(pb.id),
        provider=pb.voice_provider or "elevenlabs",
        voice_id=pb.voice_id,
        voice_name=pb.voice_name,
    )


def _field_rows(
    playbook_id: uuid.UUID,
    inputs: list[PlaybookFieldInput],
) -> list[PlaybookField]:
    seen: set[str] = set()
    rows: list[PlaybookField] = []
    for i, f in enumerate(inputs):
        if f.key in seen:
            raise PlaybookValidationError(
                f"duplicate field key: {f.key}",
                status_code=400,
            )
        seen.add(f.key)
        for pat in f.cue_patterns:
            try:
                re.compile(pat)
            except re.error as exc:
                raise PlaybookValidationError(
                    f"invalid regex for field {f.key}: {exc}",
                    status_code=400,
                ) from exc
        rows.append(
            PlaybookField(
                playbook_id=playbook_id,
                key=f.key,
                display_name=f.display_name,
                description=f.description,
                weight=f.weight,
                required=f.required,
                cue_patterns=list(f.cue_patterns or []),
                position=f.position if f.position else i,
            )
        )
    return rows


def _default_fields_for_framework(framework: str) -> list[PlaybookFieldInput]:
    from modules.playbook.seeds import _BANT_FIELDS, _MEDDICC_FIELDS

    specs = (
        _BANT_FIELDS
        if framework == PLAYBOOK_FRAMEWORK_BANT
        else _MEDDICC_FIELDS
        if framework == PLAYBOOK_FRAMEWORK_MEDDICC
        else []
    )
    return [
        PlaybookFieldInput(
            key=k,
            display_name=label,
            weight=w,
            required=req,
            position=i,
        )
        for i, (k, label, w, req) in enumerate(specs)
    ]


def _serialize_payload(playbook: Playbook, fields: list[PlaybookField]) -> dict:
    return {
        "id": str(playbook.id),
        "organization_id": str(playbook.organization_id),
        "name": playbook.name,
        "description": playbook.description,
        "status": playbook.status,
        "framework": playbook.framework,
        "persona_name": playbook.persona_name,
        "agent_name": playbook.agent_name,
        "system_prompt": playbook.system_prompt,
        "opening_line": playbook.opening_line,
        "default_objective": playbook.default_objective,
        "voice_provider": playbook.voice_provider,
        "voice_id": playbook.voice_id,
        "voice_name": playbook.voice_name,
        "voice_gender": playbook.voice_gender,
        "voice_accent": playbook.voice_accent,
        "voice_language": playbook.voice_language,
        "company_name": playbook.company_name,
        "company_intro": playbook.company_intro,
        "company_description": playbook.company_description,
        "value_proposition": playbook.value_proposition,
        "default_context": playbook.default_context,
        "disqualifying_patterns": playbook.disqualifying_patterns,
        "branches": playbook.branches or [],
        "objections": playbook.objections or [],
        "version": playbook.version,
        "fields": [
            {
                "key": f.key,
                "display_name": f.display_name,
                "description": f.description,
                "weight": f.weight,
                "required": f.required,
                "cue_patterns": f.cue_patterns or [],
                "position": f.position,
            }
            for f in sorted(fields, key=lambda x: x.position)
        ],
    }


def _to_runtime(playbook: Playbook, fields: list[PlaybookField]) -> PlaybookRuntimeConfig:
    return PlaybookRuntimeConfig(
        playbook_id=playbook.id,
        version=playbook.version,
        name=playbook.name,
        framework=playbook.framework,
        persona_name=playbook.persona_name,
        agent_name=playbook.agent_name,
        system_prompt=playbook.system_prompt,
        opening_line=playbook.opening_line,
        default_objective=playbook.default_objective,
        voice_provider=playbook.voice_provider,
        voice_id=playbook.voice_id,
        voice_name=playbook.voice_name,
        voice_gender=playbook.voice_gender,
        voice_accent=playbook.voice_accent,
        voice_language=playbook.voice_language,
        company_name=playbook.company_name,
        company_intro=playbook.company_intro,
        company_description=playbook.company_description,
        value_proposition=playbook.value_proposition,
        default_context=playbook.default_context,
        disqualifying_patterns=list(playbook.disqualifying_patterns or []),
        branches=list(playbook.branches or []),
        objections=list(playbook.objections or []),
        fields=[
            PlaybookFieldRuntime(
                key=f.key,
                display_name=f.display_name,
                description=f.description,
                weight=f.weight,
                required=f.required,
                cue_patterns=list(f.cue_patterns or []),
                position=f.position,
            )
            for f in sorted(fields, key=lambda x: x.position)
        ],
    )


def _detail(playbook: Playbook, fields: list[PlaybookField]) -> PlaybookDetail:
    return PlaybookDetail(
        id=playbook.id,
        organization_id=playbook.organization_id,
        name=playbook.name,
        description=playbook.description,
        status=playbook.status,  # type: ignore[arg-type]
        framework=playbook.framework,  # type: ignore[arg-type]
        persona_name=playbook.persona_name,
        agent_name=playbook.agent_name,
        system_prompt=playbook.system_prompt,
        opening_line=playbook.opening_line,
        default_objective=playbook.default_objective,
        voice_provider=playbook.voice_provider,
        voice_id=playbook.voice_id,
        voice_name=playbook.voice_name,
        voice_gender=playbook.voice_gender,
        voice_accent=playbook.voice_accent,
        voice_language=playbook.voice_language,
        company_name=playbook.company_name,
        company_intro=playbook.company_intro,
        company_description=playbook.company_description,
        value_proposition=playbook.value_proposition,
        default_context=playbook.default_context,
        disqualifying_patterns=playbook.disqualifying_patterns,
        branches=playbook.branches,
        objections=playbook.objections,
        version=playbook.version,
        fields=[
            PlaybookFieldOut(
                id=f.id,
                key=f.key,
                display_name=f.display_name,
                description=f.description,
                weight=f.weight,
                required=f.required,
                cue_patterns=list(f.cue_patterns or []),
                position=f.position,
                created_at=f.created_at,
                updated_at=f.updated_at,
            )
            for f in fields
        ],
        created_at=playbook.created_at,
        updated_at=playbook.updated_at,
    )


class PlaybookService:
    @staticmethod
    def list_playbooks(
        db: Session,
        organization_id: uuid.UUID,
        *,
        active_only: bool = False,
    ) -> list[PlaybookSummary]:
        status = PLAYBOOK_STATUS_ACTIVE if active_only else None
        rows = PlaybookRepository.list_for_org(
            db,
            organization_id,
            status=status,
        )
        return [
            PlaybookSummary(
                id=r.id,
                name=r.name,
                description=r.description,
                status=r.status,  # type: ignore[arg-type]
                framework=r.framework,  # type: ignore[arg-type]
                persona_name=r.persona_name,
                version=r.version,
                field_count=PlaybookRepository.count_fields(db, r.id),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    @staticmethod
    def get_for_dialer(
        db: Session,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
    ) -> PlaybookDetail:
        """Load a playbook for the phone dialer and log selection.

        Only **active** (published) playbooks may be used on live calls.
        """

        detail = PlaybookService.get(db, organization_id, playbook_id)
        if detail.status != PLAYBOOK_STATUS_ACTIVE:
            raise PlaybookValidationError(
                "This playbook must be published before it can be used on a call. "
                "Open Playbooks and click Publish."
            )
        log.info(
            "playbook.PLAYBOOK_SELECTED",
            playbook_id=str(playbook_id),
            playbook_name=detail.name,
            framework=detail.framework,
            voice_id=detail.voice_id,
        )
        return detail

    @staticmethod
    def get(
        db: Session,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
    ) -> PlaybookDetail:
        pb = PlaybookRepository.get(
            db, playbook_id, organization_id=organization_id
        )
        if pb is None:
            raise PlaybookNotFoundError("Playbook not found")
        fields = list(
            db.query(PlaybookField)
            .filter(PlaybookField.playbook_id == pb.id)
            .order_by(PlaybookField.position.asc())
            .all()
        )
        return _detail(pb, fields)

    @staticmethod
    def create(
        db: Session,
        organization_id: uuid.UUID,
        created_by: uuid.UUID | None,
        data: CreatePlaybookInput,
    ) -> PlaybookDetail:
        if PlaybookRepository.get_by_name(
            db, organization_id=organization_id, name=data.name.strip()
        ):
            raise PlaybookConflictError(
                f"A playbook named '{data.name}' already exists"
            )

        fields_in = data.fields
        if not fields_in and data.framework != PLAYBOOK_FRAMEWORK_CUSTOM:
            fields_in = _default_fields_for_framework(data.framework)

        pb = Playbook(
            organization_id=organization_id,
            created_by=created_by,
            name=data.name.strip(),
            description=data.description,
            status=PLAYBOOK_STATUS_DRAFT,
            framework=data.framework,
            persona_name=data.persona_name,
            agent_name=data.agent_name,
            system_prompt=data.system_prompt,
            opening_line=data.opening_line,
            default_objective=data.default_objective,
            voice_provider=data.voice_provider,
            voice_id=data.voice_id,
            voice_name=data.voice_name,
            voice_gender=data.voice_gender,
            voice_accent=data.voice_accent,
            voice_language=data.voice_language,
            company_name=data.company_name,
            company_intro=data.company_intro,
            company_description=data.company_description,
            value_proposition=data.value_proposition,
            default_context=data.default_context,
            disqualifying_patterns=data.disqualifying_patterns or None,
            branches=[b.model_dump() for b in data.branches] if data.branches else None,
            objections=(
                [o.model_dump() for o in data.objections]
                if data.objections
                else None
            ),
            version=1,
        )
        validate_company_fields(pb)
        PlaybookRepository.create(db, pb)
        field_rows = _field_rows(pb.id, fields_in)
        PlaybookRepository.replace_fields(db, pb.id, field_rows)
        db.commit()
        db.refresh(pb)
        _log_voice_selected(pb, action="create")
        return _detail(pb, field_rows)

    @staticmethod
    def update(
        db: Session,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
        data: UpdatePlaybookInput,
    ) -> PlaybookDetail:
        pb = PlaybookRepository.get(
            db, playbook_id, organization_id=organization_id, with_fields=False
        )
        if pb is None:
            raise PlaybookNotFoundError("Playbook not found")
        if pb.status == PLAYBOOK_STATUS_ARCHIVED:
            raise PlaybookConflictError(
                "Cannot edit an archived playbook — duplicate it first"
            )

        if data.name is not None:
            name = data.name.strip()
            existing = PlaybookRepository.get_by_name(
                db, organization_id=organization_id, name=name
            )
            if existing and existing.id != pb.id:
                raise PlaybookConflictError(
                    f"A playbook named '{name}' already exists"
                )
            pb.name = name

        if data.branches is not None:
            pb.branches = [b.model_dump() for b in data.branches]

        if data.objections is not None:
            pb.objections = [o.model_dump() for o in data.objections]

        voice_changed = False
        for attr in (
            "description",
            "framework",
            "persona_name",
            "agent_name",
            "system_prompt",
            "opening_line",
            "default_objective",
            "voice_provider",
            "voice_id",
            "voice_name",
            "voice_gender",
            "voice_accent",
            "voice_language",
            "company_name",
            "company_intro",
            "company_description",
            "value_proposition",
            "default_context",
            "disqualifying_patterns",
        ):
            val = getattr(data, attr)
            if val is not None:
                setattr(pb, attr, val)
                if attr.startswith("voice_"):
                    voice_changed = True

        validate_company_fields(pb)

        field_rows: list[PlaybookField] | None = None
        if data.fields is not None:
            field_rows = _field_rows(pb.id, data.fields)
            PlaybookRepository.replace_fields(db, pb.id, field_rows)

        db.commit()
        db.refresh(pb)
        if voice_changed:
            _log_voice_selected(pb, action="update")
        if field_rows is None:
            field_rows = list(
                db.query(PlaybookField)
                .filter(PlaybookField.playbook_id == pb.id)
                .order_by(PlaybookField.position.asc())
                .all()
            )
        return _detail(pb, field_rows)

    @staticmethod
    def publish(
        db: Session,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
        created_by: uuid.UUID | None,
    ) -> PlaybookDetail:
        pb = PlaybookRepository.get(
            db, playbook_id, organization_id=organization_id, with_fields=False
        )
        if pb is None:
            raise PlaybookNotFoundError("Playbook not found")
        if pb.status == PLAYBOOK_STATUS_ARCHIVED:
            raise PlaybookConflictError("Cannot publish an archived playbook")

        fields = list(
            db.query(PlaybookField)
            .filter(PlaybookField.playbook_id == pb.id)
            .order_by(PlaybookField.position.asc())
            .all()
        )
        if not fields:
            raise PlaybookValidationError(
                "Cannot publish a playbook with no qualification fields"
            )

        validate_company_fields(pb)

        pb.version += 1
        pb.status = PLAYBOOK_STATUS_ACTIVE
        payload = _serialize_payload(pb, fields)
        PlaybookVersionRepository.create(
            db,
            PlaybookVersion(
                playbook_id=pb.id,
                organization_id=organization_id,
                created_by=created_by,
                version=pb.version,
                payload=payload,
            ),
        )
        db.commit()
        db.refresh(pb)
        return _detail(pb, fields)

    @staticmethod
    def archive(
        db: Session,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
    ) -> PlaybookDetail:
        pb = PlaybookRepository.get(
            db, playbook_id, organization_id=organization_id, with_fields=False
        )
        if pb is None:
            raise PlaybookNotFoundError("Playbook not found")
        pb.status = PLAYBOOK_STATUS_ARCHIVED
        db.commit()
        fields = list(
            db.query(PlaybookField)
            .filter(PlaybookField.playbook_id == pb.id)
            .order_by(PlaybookField.position.asc())
            .all()
        )
        return _detail(pb, fields)

    @staticmethod
    def duplicate(
        db: Session,
        organization_id: uuid.UUID,
        created_by: uuid.UUID | None,
        playbook_id: uuid.UUID,
    ) -> PlaybookDetail:
        source = PlaybookRepository.get(
            db, playbook_id, organization_id=organization_id, with_fields=False
        )
        if source is None:
            raise PlaybookNotFoundError("Playbook not found")

        base_name = f"{source.name} (copy)"
        name = base_name
        n = 2
        while PlaybookRepository.get_by_name(
            db, organization_id=organization_id, name=name
        ):
            name = f"{source.name} (copy {n})"
            n += 1

        fields = list(
            db.query(PlaybookField)
            .filter(PlaybookField.playbook_id == source.id)
            .order_by(PlaybookField.position.asc())
            .all()
        )

        pb = Playbook(
            organization_id=organization_id,
            created_by=created_by,
            name=name,
            description=source.description,
            status=PLAYBOOK_STATUS_DRAFT,
            framework=source.framework,
            persona_name=source.persona_name,
            agent_name=source.agent_name,
            system_prompt=source.system_prompt,
            opening_line=source.opening_line,
            default_objective=source.default_objective,
            voice_provider=source.voice_provider,
            voice_id=source.voice_id,
            voice_name=source.voice_name,
            voice_gender=source.voice_gender,
            voice_accent=source.voice_accent,
            voice_language=source.voice_language,
            company_name=source.company_name,
            company_intro=source.company_intro,
            company_description=source.company_description,
            value_proposition=source.value_proposition,
            default_context=source.default_context,
            disqualifying_patterns=source.disqualifying_patterns,
            branches=list(source.branches or []) if source.branches else None,
            objections=list(source.objections or []) if source.objections else None,
            version=1,
        )
        PlaybookRepository.create(db, pb)
        new_fields = [
            PlaybookField(
                playbook_id=pb.id,
                key=f.key,
                display_name=f.display_name,
                description=f.description,
                weight=f.weight,
                required=f.required,
                cue_patterns=f.cue_patterns,
                position=f.position,
            )
            for f in fields
        ]
        PlaybookRepository.replace_fields(db, pb.id, new_fields)
        db.commit()
        db.refresh(pb)
        return _detail(pb, new_fields)

    @staticmethod
    def list_versions(
        db: Session,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
    ) -> list[PlaybookVersionOut]:
        pb = PlaybookRepository.get(
            db, playbook_id, organization_id=organization_id, with_fields=False
        )
        if pb is None:
            raise PlaybookNotFoundError("Playbook not found")
        rows = PlaybookVersionRepository.list_for_playbook(
            db, playbook_id, organization_id=organization_id
        )
        return [PlaybookVersionOut.model_validate(r) for r in rows]

    @staticmethod
    def resolve_for_call(
        db: Session,
        *,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
        version: int | None = None,
        allow_draft: bool = False,
    ) -> PlaybookRuntimeConfig:
        """Load an active playbook (or a specific version snapshot) for a call."""

        if version is not None:
            snap = PlaybookVersionRepository.get_version(
                db, playbook_id, version
            )
            if snap is None or snap.organization_id != organization_id:
                raise PlaybookNotFoundError("Playbook version not found")
            payload = snap.payload
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
                for f in payload.get("fields", [])
            ]
            return PlaybookRuntimeConfig(
                playbook_id=playbook_id,
                version=snap.version,
                name=payload.get("name", ""),
                framework=payload.get("framework", PLAYBOOK_FRAMEWORK_BANT),
                persona_name=payload.get("persona_name", "outbound_sdr"),
                agent_name=payload.get("agent_name"),
                system_prompt=payload.get("system_prompt"),
                opening_line=payload.get("opening_line"),
                default_objective=payload.get("default_objective"),
                voice_provider=payload.get("voice_provider"),
                voice_id=payload.get("voice_id"),
                voice_name=payload.get("voice_name"),
                voice_gender=payload.get("voice_gender"),
                voice_accent=payload.get("voice_accent"),
                voice_language=payload.get("voice_language"),
                company_name=payload.get("company_name"),
                company_intro=payload.get("company_intro"),
                company_description=payload.get("company_description"),
                value_proposition=payload.get("value_proposition"),
                default_context=payload.get("default_context"),
                disqualifying_patterns=list(
                    payload.get("disqualifying_patterns") or []
                ),
                branches=list(payload.get("branches") or []),
                objections=list(payload.get("objections") or []),
                fields=fields,
            )

        pb = PlaybookRepository.get(
            db, playbook_id, organization_id=organization_id, with_fields=False
        )
        if pb is None:
            raise PlaybookNotFoundError("Playbook not found")
        if pb.status != PLAYBOOK_STATUS_ACTIVE and not allow_draft:
            raise PlaybookValidationError(
                "Playbook must be active to use on a call — publish it first"
            )
        if pb.status == PLAYBOOK_STATUS_ARCHIVED:
            raise PlaybookValidationError("Cannot use an archived playbook")
        fields = list(
            db.query(PlaybookField)
            .filter(PlaybookField.playbook_id == pb.id)
            .order_by(PlaybookField.position.asc())
            .all()
        )
        return _to_runtime(pb, fields)

    @staticmethod
    def preview_prompt(
        db: Session,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
        extra_context: dict[str, Any] | None = None,
    ) -> PlaybookPromptPreview:
        runtime = PlaybookService.resolve_for_call(
            db, organization_id=organization_id, playbook_id=playbook_id, allow_draft=True
        )
        merged = {**(runtime.default_context or {}), **(extra_context or {})}
        if runtime.default_objective:
            merged.setdefault("objective", runtime.default_objective)
        rendered = render_system_prompt(
            persona=runtime.persona_name,
            framework=runtime.framework,
            extra_context=merged,
            playbook=runtime,
        )
        placeholders = sorted(set(re.findall(r"\{(\w+)\}", rendered)))
        return PlaybookPromptPreview(
            rendered_system_prompt=rendered,
            placeholders=placeholders,
        )

    @staticmethod
    def test_turn(
        db: Session,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
        data: PlaybookTestInput,
    ) -> PlaybookTestResponse:
        runtime = PlaybookService.resolve_for_call(
            db, organization_id=organization_id, playbook_id=playbook_id, allow_draft=True
        )
        merged = {
            **(runtime.default_context or {}),
            **(data.extra_context or {}),
        }
        if runtime.default_objective:
            merged.setdefault("objective", runtime.default_objective)

        fw = (
            QualificationFramework(runtime.framework)
            if runtime.framework in ("BANT", "MEDDICC")
            else QualificationFramework.BANT
        )
        before = QualificationTracker.empty_from_playbook(runtime, fw)
        after = QualificationTracker.empty_from_playbook(runtime, fw)
        newly = after.ingest_user_turn(data.user_text)
        newly_clean = [f for f in newly if f != "__disqualified__"]

        branch_out = evaluate_branches(
            parse_branch_rules(runtime.branches),
            after,
            newly_set_fields=newly_clean,
            branches_fired=[],
        )
        if branch_out.switch_persona:
            runtime_persona = branch_out.switch_persona
        else:
            runtime_persona = runtime.persona_name
        if branch_out.objective:
            merged["objective"] = branch_out.objective
        if branch_out.merge_context:
            merged.update(branch_out.merge_context)
        if branch_out.dynamic_block:
            merged["dynamic_block"] = branch_out.dynamic_block

        objection_rules = parse_objections(runtime.objections)
        objection_match = match_objection(data.user_text, objection_rules)
        objection_out: ObjectionMatchOut | None = None
        if objection_match:
            instruction = objection_turn_instruction(objection_match)
            existing = merged.get("dynamic_block")
            merged["dynamic_block"] = (
                f"{existing}\n\n{instruction}" if existing else instruction
            )
            rule = objection_match.rule
            objection_out = ObjectionMatchOut(
                objection_type=rule.objection_type,
                objection_trigger=rule.objection_trigger,
                objection_response=rule.objection_response,
                fallback_response=rule.fallback_response,
                score=objection_match.score,
                strategy=objection_match.strategy,
            )

        rendered = render_system_prompt(
            persona=runtime_persona,
            framework=runtime.framework,
            extra_context=merged,
            playbook=runtime,
        )
        return PlaybookTestResponse(
            rendered_system_prompt=rendered,
            qualification_before=before.snapshot().model_dump(),
            qualification_after=after.snapshot().model_dump(),
            newly_set_fields=newly_clean,
            branches_fired=branch_out.fired_branch_ids,
            objection_matched=objection_out,
        )
