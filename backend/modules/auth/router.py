from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from common.security.authorization import require_role
from common.security.dependencies import get_current_user
from common.security.roles import Role
from common.security.status import MembershipStatus
from database.dependencies import get_db
from modules.auth.audit_model import AuditLog
from modules.auth.dependencies import get_current_org
from modules.auth.membership_model import Membership
from modules.auth.model import User
from modules.auth.organization_model import Organization
from modules.auth.repository import AuthRepository
from modules.auth.schema import (
    AuditEntry,
    AuditListResponse,
    ForgotPasswordInput,
    LoginInput,
    LogoutInput,
    RefreshInput,
    RegisterInput,
    ResetPasswordInput,
)
from modules.auth.service import AuthService
from modules.auth.tenant import get_current_tenant

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.post("/register")
async def register(
    data: RegisterInput,
    db: Session = Depends(get_db),
):
    return AuthService.register(db, data)


@router.post("/login")
async def login(
    data: LoginInput,
    db: Session = Depends(get_db),
):
    return AuthService.login(db, data)


@router.get("/me")
async def me(
    payload=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = AuthRepository.get_user_by_id(db, payload["sub"])
    if not user:
        raise HTTPException(404, "User not found")

    role_rank = case(
        (Membership.role == Role.OWNER, 0),
        (Membership.role == Role.ADMIN, 1),
        (Membership.role == Role.AGENT, 2),
        (Membership.role == Role.MEMBER, 3),
        else_=99,
    )
    status_rank = case(
        (Membership.status == MembershipStatus.ACTIVE, 0),
        else_=1,
    )
    row = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id)
        .order_by(status_rank, role_rank, Membership.created_at.desc())
        .limit(1)
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
async def org(org=Depends(get_current_org)):
    return org


@router.get("/tenant")
async def tenant(tenant=Depends(get_current_tenant)):
    return tenant


@router.get("/admin")
async def admin(tenant=Depends(get_current_tenant)):
    require_role([Role.OWNER, Role.ADMIN])(tenant)
    return {"message": "admin access"}


@router.post("/refresh")
async def refresh(
    data: RefreshInput,
    db: Session = Depends(get_db),
):
    return AuthService.refresh(db, data)


@router.post("/logout")
async def logout(
    data: LogoutInput,
    db: Session = Depends(get_db),
):
    return AuthService.logout(db, data)


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordInput,
    db: Session = Depends(get_db),
):
    return AuthService.forgot_password(db, data)


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordInput,
    db: Session = Depends(get_db),
):
    return AuthService.reset_password(db, data)


@router.get("/audit", response_model=AuditListResponse)
async def audit(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """List audit entries for users in the caller's organization only.

    Owners and admins see the full org log; agents and members only see
    their own events.
    """
    role = str(tenant.get("role"))
    user_id = tenant.get("user_id")
    org_id = tenant.get("organization_id")

    # Compute the user-id set to scope the audit query.
    if role in (Role.OWNER.value, Role.ADMIN.value):
        # All users who currently belong to this org.
        user_ids_stmt = (
            select(User.id)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.organization_id == org_id)
        )
        scope_filter = AuditLog.user_id.in_(user_ids_stmt)
    else:
        # Lower roles only see their own audit trail.
        scope_filter = AuditLog.user_id == user_id

    total = db.execute(
        select(func.count()).select_from(AuditLog).where(scope_filter)
    ).scalar_one()

    rows = (
        db.execute(
            select(AuditLog)
            .where(scope_filter)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )

    return AuditListResponse(
        entries=[AuditEntry.model_validate(r) for r in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )
