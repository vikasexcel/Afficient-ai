"""HTTP API for playbook management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.auth.tenant import get_current_tenant
from modules.playbook.exceptions import PlaybookError
from modules.playbook.schema import (
    CreatePlaybookInput,
    PlaybookDetail,
    PlaybookListResponse,
    PlaybookPromptPreview,
    PlaybookSummary,
    PlaybookTestInput,
    PlaybookTestResponse,
    PlaybookVersionListResponse,
    UpdatePlaybookInput,
)
from modules.playbook.seeds import seed_defaults_for_org
from modules.playbook.service import PlaybookService

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


def _org_id(tenant: dict) -> uuid.UUID:
    return uuid.UUID(str(tenant["organization_id"]))


def _user_id(tenant: dict) -> uuid.UUID | None:
    uid = tenant.get("user_id")
    return uuid.UUID(str(uid)) if uid else None


def _to_http(exc: PlaybookError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=PlaybookListResponse)
def list_playbooks(
    active_only: bool = False,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    org = _org_id(tenant)
    seed_defaults_for_org(db, organization_id=org, created_by=_user_id(tenant))
    db.commit()
    playbooks = PlaybookService.list_playbooks(
        db, org, active_only=active_only
    )
    return PlaybookListResponse(playbooks=playbooks)


@router.post("", response_model=PlaybookDetail, status_code=201)
def create_playbook(
    data: CreatePlaybookInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    try:
        return PlaybookService.create(
            db, _org_id(tenant), _user_id(tenant), data
        )
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.get("/{playbook_id}", response_model=PlaybookDetail)
def get_playbook(
    playbook_id: uuid.UUID,
    for_dialer: bool = False,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Return playbook detail.

    When ``for_dialer=true`` (phone dialer), only active playbooks are
    accepted and ``PLAYBOOK_SELECTED`` is logged.
    """
    try:
        org = _org_id(tenant)
        if for_dialer:
            return PlaybookService.get_for_dialer(db, org, playbook_id)
        return PlaybookService.get(db, org, playbook_id)
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.patch("/{playbook_id}", response_model=PlaybookDetail)
def update_playbook(
    playbook_id: uuid.UUID,
    data: UpdatePlaybookInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    try:
        return PlaybookService.update(
            db, _org_id(tenant), playbook_id, data
        )
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.post("/{playbook_id}/publish", response_model=PlaybookDetail)
def publish_playbook(
    playbook_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    try:
        return PlaybookService.publish(
            db, _org_id(tenant), playbook_id, _user_id(tenant)
        )
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.post("/{playbook_id}/archive", response_model=PlaybookDetail)
def archive_playbook(
    playbook_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    try:
        return PlaybookService.archive(db, _org_id(tenant), playbook_id)
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.delete("/{playbook_id}", status_code=204)
def delete_playbook(
    playbook_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    """Permanently delete a playbook (hard delete).

    Use ``POST /{id}/archive`` when you want to soft-delete instead.
    """
    try:
        PlaybookService.delete(db, _org_id(tenant), playbook_id)
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.post("/{playbook_id}/duplicate", response_model=PlaybookDetail)
def duplicate_playbook(
    playbook_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    try:
        return PlaybookService.duplicate(
            db, _org_id(tenant), _user_id(tenant), playbook_id
        )
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.get(
    "/{playbook_id}/versions",
    response_model=PlaybookVersionListResponse,
)
def list_versions(
    playbook_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    try:
        versions = PlaybookService.list_versions(
            db, _org_id(tenant), playbook_id
        )
        return PlaybookVersionListResponse(versions=versions)
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.post(
    "/{playbook_id}/test",
    response_model=PlaybookTestResponse,
)
def test_playbook(
    playbook_id: uuid.UUID,
    data: PlaybookTestInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    try:
        return PlaybookService.test_turn(
            db, _org_id(tenant), playbook_id, data
        )
    except PlaybookError as exc:
        raise _to_http(exc) from exc


@router.get(
    "/{playbook_id}/preview",
    response_model=PlaybookPromptPreview,
)
def preview_prompt(
    playbook_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    try:
        return PlaybookService.preview_prompt(
            db, _org_id(tenant), playbook_id
        )
    except PlaybookError as exc:
        raise _to_http(exc) from exc
