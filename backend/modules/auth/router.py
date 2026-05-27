from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.dependencies import get_db
from modules.auth.schema import RegisterInput
from modules.auth.service import AuthService
from modules.auth.schema import (
    LoginInput
)
from common.security.dependencies import (
    get_current_user
)
from modules.auth.dependencies import (
    get_current_org
)
from modules.auth.tenant import (
    get_current_tenant
)
from common.security.roles import Role
from common.security.authorization import (
    require_role
)
from modules.auth.repository import AuthRepository
from modules.auth.membership_model import Membership
from modules.auth.organization_model import Organization

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)
from modules.auth.schema import (
    RefreshInput
)
from modules.auth.schema import (
    LogoutInput
)
from modules.auth.audit_model import (
    AuditLog
)


@router.post("/register")
async def register(
    data: RegisterInput,
    db: Session = Depends(get_db),
):
    return AuthService.register(db,data,)



@router.post("/login")
async def login(
    data:LoginInput,
    db: Session =Depends(get_db),
):
    return (AuthService.login(db,data,))




@router.get("/me")
async def me(
    payload=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = AuthRepository.get_user_by_id(db, payload["sub"])
    if not user:
        raise HTTPException(404, "User not found")

    row = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id)
    ).first()

    membership = row[0] if row else None
    org = row[1] if row else None

    return {
        "id": str(user.id),
        "full_name": user.full_name,
        "email": user.email,
        "role": (
            membership.role.value
            if membership and hasattr(membership.role, "value")
            else (str(membership.role) if membership else None)
        ),
        "membership_id": str(membership.id) if membership else None,
        "organization": (
            {"id": str(org.id), "name": org.name} if org else None
        ),
    }




@router.get("/org")
async def org(org=Depends(get_current_org),):
    return org



@router.get("/tenant")
async def tenant(
    tenant=Depends(get_current_tenant),
):

    return tenant


@router.get("/admin")
async def admin(
    tenant=Depends(get_current_tenant),
):

    require_role([
        Role.OWNER,
        Role.ADMIN,
    ])(tenant)

    return {"message":"admin access"}


@router.post("/refresh")
async def refresh(
    data:RefreshInput,
    db:Session =Depends(get_db),
):
    return (AuthService.refresh(db,data,))


@router.post("/logout")
async def logout(
    data:LogoutInput,
    db:Session = Depends(get_db),
):
    return (AuthService.logout(db,data,))


@router.get("/audit")
async def audit(
    db:Session = Depends(get_db),
):
    return (
        db.query(AuditLog).all())