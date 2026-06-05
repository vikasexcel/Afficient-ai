from fastapi import Depends, HTTPException
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from common.security.dependencies import get_current_user
from common.security.roles import Role
from common.security.status import MembershipStatus
from database.dependencies import get_db
from modules.auth.membership_model import Membership


# Order memberships so the user lands in their most relevant tenant when they
# belong to several organizations. Higher-privileged + ACTIVE memberships win,
# with the most recently created one as the final tiebreaker.
_ROLE_RANK = case(
    (Membership.role == Role.OWNER, 0),
    (Membership.role == Role.ADMIN, 1),
    (Membership.role == Role.AGENT, 2),
    (Membership.role == Role.MEMBER, 3),
    else_=99,
)

_STATUS_RANK = case(
    (Membership.status == MembershipStatus.ACTIVE, 0),
    else_=1,
)


def resolve_tenant(db: Session, user_id) -> dict:
    """Resolve a user's primary tenant context.

    Factored out of :func:`get_current_tenant` so non-FastAPI-dependency
    callers (e.g. the internal-or-tenant auth path on the telephony router)
    can reuse the exact same membership-ranking logic.
    """

    stmt = (
        select(Membership)
        .where(Membership.user_id == user_id)
        .order_by(_STATUS_RANK, _ROLE_RANK, Membership.created_at.desc())
        .limit(1)
    )

    membership = db.execute(stmt).scalars().first()

    if not membership:
        raise HTTPException(403, "Tenant not found")

    return {
        "user_id": user_id,
        "organization_id": str(membership.organization_id),
        "membership_id": str(membership.id),
        "role": membership.role.value
        if hasattr(membership.role, "value")
        else str(membership.role),
        "status": membership.status.value
        if hasattr(membership.status, "value")
        else str(membership.status),
    }


async def get_current_tenant(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return resolve_tenant(db, user["sub"])