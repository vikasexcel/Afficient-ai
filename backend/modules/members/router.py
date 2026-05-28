from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.auth.tenant import get_current_tenant
from modules.members.schema import (
    CreateMemberInput,
    CreateMemberOut,
    MemberOut,
    RemoveMemberOut,
    ResetPasswordOut,
    UpdateRoleInput,
)
from modules.members.service import MembersService

router = APIRouter(prefix="/members", tags=["members"])


@router.get("", response_model=list[MemberOut])
def list_members(
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    return MembersService.list(db, tenant)


@router.post("", response_model=CreateMemberOut, status_code=201)
def create_member(
    data: CreateMemberInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    return MembersService.create(db, tenant, data)


@router.patch("/{membership_id}/role", response_model=MemberOut)
def update_role(
    membership_id: str,
    data: UpdateRoleInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    return MembersService.update_role(db, tenant, membership_id, data.role)


@router.post(
    "/{membership_id}/reset-password",
    response_model=ResetPasswordOut,
)
def reset_password(
    membership_id: str,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    return MembersService.reset_password(db, tenant, membership_id)


@router.delete("/{membership_id}", response_model=RemoveMemberOut)
def remove_member(
    membership_id: str,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    return MembersService.remove(db, tenant, membership_id)
