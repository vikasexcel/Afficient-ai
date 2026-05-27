import secrets

from fastapi import HTTPException
from sqlalchemy.orm import Session

from common.security.password import hash_password
from common.security.roles import Role
from common.security.status import MembershipStatus
from modules.auth.audit_model import AuditLog
from modules.auth.membership_model import Membership
from modules.auth.model import User
from modules.auth.repository import AuthRepository
from modules.members.repository import MembersRepository


def _gen_temp_password() -> str:
    return secrets.token_urlsafe(12)


def _serialize(membership: Membership, user: User) -> dict:
    return {
        "membership_id": str(membership.id),
        "user_id": str(user.id),
        "full_name": user.full_name,
        "email": user.email,
        "role": membership.role.value
        if hasattr(membership.role, "value")
        else str(membership.role),
        "status": membership.status.value
        if hasattr(membership.status, "value")
        else str(membership.status),
    }


def _log(db, user_id, action, details):
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            details=details,
        )
    )


class MembersService:

    @staticmethod
    def list(db: Session, tenant) -> list[dict]:
        rows = MembersRepository.list_by_org(db, tenant["organization_id"])
        return [_serialize(m, u) for m, u in rows]

    @staticmethod
    def create(db: Session, tenant, data) -> dict:
        existing_user = AuthRepository.get_user(db, data.email)
        temp_password = data.password or _gen_temp_password()

        if existing_user is None:
            user = User(
                full_name=data.full_name,
                email=data.email,
                password_hash=hash_password(temp_password),
            )
            user = AuthRepository.create_user(db, user)
        else:
            user = existing_user
            existing_membership = (
                db.query(Membership)
                .filter(
                    Membership.user_id == user.id,
                    Membership.organization_id == tenant["organization_id"],
                )
                .first()
            )
            if existing_membership:
                raise HTTPException(409, "User is already a member")

        membership = Membership(
            user_id=user.id,
            organization_id=tenant["organization_id"],
            role=data.role.value,
            status=MembershipStatus.PENDING
            if data.password is None
            else MembershipStatus.ACTIVE,
        )
        AuthRepository.create_membership(db, membership)

        _log(
            db,
            tenant["user_id"],
            "MEMBER_CREATED",
            f"{user.email} role={data.role.value}",
        )

        db.commit()
        db.refresh(membership)
        return {
            "member": _serialize(membership, user),
            "temp_password": temp_password if data.password is None else None,
        }

    @staticmethod
    def update_role(db: Session, tenant, membership_id: str, new_role: Role) -> dict:
        row = MembersRepository.get_membership_with_user(
            db, membership_id, tenant["organization_id"]
        )
        if row is None:
            raise HTTPException(404, "Member not found")
        membership, user = row

        actor_role = tenant["role"]
        target_role = (
            membership.role.value
            if hasattr(membership.role, "value")
            else str(membership.role)
        )

        # Only OWNER can change OWNER role (e.g., during transfer) or promote to OWNER
        if (
            target_role == Role.OWNER.value or new_role == Role.OWNER
        ) and actor_role != Role.OWNER.value:
            raise HTTPException(403, "Only the Owner can change ownership")

        # Prevent demoting the last Owner
        if (
            target_role == Role.OWNER.value
            and new_role != Role.OWNER
            and _owner_count(db, tenant["organization_id"]) <= 1
        ):
            raise HTTPException(400, "Cannot demote the only Owner")

        membership.role = new_role.value

        _log(
            db,
            tenant["user_id"],
            "MEMBER_ROLE_UPDATED",
            f"{user.email} -> {new_role.value}",
        )
        db.commit()
        db.refresh(membership)
        return _serialize(membership, user)

    @staticmethod
    def reset_password(db: Session, tenant, membership_id: str) -> dict:
        row = MembersRepository.get_membership_with_user(
            db, membership_id, tenant["organization_id"]
        )
        if row is None:
            raise HTTPException(404, "Member not found")
        membership, user = row

        temp = _gen_temp_password()
        user.password_hash = hash_password(temp)
        membership.status = MembershipStatus.PENDING

        _log(
            db,
            tenant["user_id"],
            "MEMBER_PASSWORD_RESET",
            user.email,
        )
        db.commit()
        return {"temp_password": temp}

    @staticmethod
    def remove(db: Session, tenant, membership_id: str):
        row = MembersRepository.get_membership_with_user(
            db, membership_id, tenant["organization_id"]
        )
        if row is None:
            raise HTTPException(404, "Member not found")
        membership, user = row

        target_role = (
            membership.role.value
            if hasattr(membership.role, "value")
            else str(membership.role)
        )

        if target_role == Role.OWNER.value:
            raise HTTPException(400, "Cannot remove the Owner. Transfer ownership first.")

        if str(membership.user_id) == tenant["user_id"]:
            raise HTTPException(400, "You cannot remove yourself")

        _log(
            db,
            tenant["user_id"],
            "MEMBER_REMOVED",
            user.email,
        )
        db.delete(membership)
        db.commit()


def _owner_count(db: Session, organization_id: str) -> int:
    return (
        db.query(Membership)
        .filter(
            Membership.organization_id == organization_id,
            Membership.role == Role.OWNER.value,
        )
        .count()
    )
