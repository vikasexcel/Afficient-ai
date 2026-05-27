from fastapi import Depends
from fastapi import HTTPException

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.dependencies import get_db

from common.security.dependencies import (
    get_current_user,
)

from modules.auth.membership_model import Membership


async def get_current_tenant(

    user=Depends(
        get_current_user
    ),

    db: Session = Depends(
        get_db
    ),

):

    stmt = (
        select(
            Membership
        )
        .where(
            Membership.user_id
            == user["sub"]
        )
    )

    membership = (
        db.execute(
            stmt
        )
        .scalar_one_or_none()
    )

    if not membership:

        raise HTTPException(
            403,
            "Tenant not found",
        )

    return {
        "user_id": user["sub"],
        "organization_id": str(membership.organization_id),
        "membership_id": str(membership.id),
        "role": membership.role.value if hasattr(membership.role, "value") else str(membership.role),
        "status": membership.status.value if hasattr(membership.status, "value") else str(membership.status),
    }