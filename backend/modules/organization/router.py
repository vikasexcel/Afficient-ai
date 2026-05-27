from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.auth.audit_model import AuditLog
from modules.auth.membership_model import Membership
from modules.auth.organization_model import Organization
from modules.auth.tenant import get_current_tenant
from modules.organization.schema import (
    OrganizationOut,
    RenameInput,
    TransferOwnershipInput,
)

router = APIRouter(prefix="/organization", tags=["organization"])


def _get_org_or_404(db: Session, organization_id: str) -> Organization:
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    return org


@router.get("", response_model=OrganizationOut)
def get_org(
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    org = _get_org_or_404(db, tenant["organization_id"])
    return {"id": str(org.id), "name": org.name}


@router.patch("", response_model=OrganizationOut)
def rename_org(
    data: RenameInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
):
    org = _get_org_or_404(db, tenant["organization_id"])
    org.name = data.name
    db.add(
        AuditLog(
            user_id=tenant["user_id"],
            action="ORG_RENAMED",
            details=data.name,
        )
    )
    db.commit()
    db.refresh(org)
    return {"id": str(org.id), "name": org.name}


@router.post("/transfer-ownership", status_code=204)
def transfer_ownership(
    data: TransferOwnershipInput,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER)),
):
    target = (
        db.query(Membership)
        .filter(
            Membership.id == data.membership_id,
            Membership.organization_id == tenant["organization_id"],
        )
        .first()
    )
    if not target:
        raise HTTPException(404, "Target member not found")
    if str(target.id) == tenant["membership_id"]:
        raise HTTPException(400, "You are already the Owner")

    current_owner = (
        db.query(Membership)
        .filter(Membership.id == tenant["membership_id"])
        .first()
    )

    target.role = Role.OWNER.value
    current_owner.role = Role.ADMIN.value

    db.add(
        AuditLog(
            user_id=tenant["user_id"],
            action="ORG_OWNERSHIP_TRANSFERRED",
            details=str(target.id),
        )
    )
    db.commit()
    return None


@router.delete("", status_code=204)
def delete_org(
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER)),
):
    org = _get_org_or_404(db, tenant["organization_id"])
    db.query(Membership).filter(
        Membership.organization_id == org.id
    ).delete(synchronize_session=False)
    db.delete(org)
    db.commit()
    return None
