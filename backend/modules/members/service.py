import logging
import secrets

from fastapi import HTTPException
from sqlalchemy.orm import Session

from common.email.mailer import send_email_async
from common.email.templates import (
    member_invitation_email,
    member_removed_email,
    password_reset_email,
)
from common.security.password import hash_password
from common.security.roles import Role
from common.security.status import MembershipStatus
from modules.auth.audit_model import AuditLog
from modules.auth.membership_model import Membership
from modules.auth.model import User
from modules.auth.organization_model import Organization
from modules.auth.repository import AuthRepository
from modules.members.repository import MembersRepository

logger = logging.getLogger(__name__)


def _gen_temp_password() -> str:
    """Generate a URL-safe 16-char temporary password."""
    return secrets.token_urlsafe(12)


def _role_str(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


def _serialize(membership: Membership, user: User) -> dict:
    return {
        "membership_id": str(membership.id),
        "user_id": str(user.id),
        "full_name": user.full_name,
        "email": user.email,
        "role": _role_str(membership.role),
        "status": membership.status.value
        if hasattr(membership.status, "value")
        else str(membership.status),
    }


def _log(db: Session, user_id, action: str, details: str) -> None:
    db.add(AuditLog(user_id=user_id, action=action, details=details))
    logger.info("audit user=%s action=%s details=%s", user_id, action, details)


class MembersService:

    @staticmethod
    def list(db: Session, tenant) -> list[dict]:
        rows = MembersRepository.list_by_org(db, tenant["organization_id"])
        return [_serialize(m, u) for m, u in rows]

    @staticmethod
    def create(db: Session, tenant, data) -> dict:
        email = data.email.strip().lower()
        existing_user = AuthRepository.get_user(db, email)
        account_exists = existing_user is not None

        if existing_user is None:
            temp_password = data.password or _gen_temp_password()
            user = User(
                full_name=data.full_name,
                email=email,
                password_hash=hash_password(temp_password),
            )
            user = AuthRepository.create_user(db, user)
        else:
            user = existing_user
            temp_password = None
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

        # PENDING when admin issued a temp password the member must change later;
        # ACTIVE when admin set an explicit password or the user already has an account.
        if account_exists or data.password is not None:
            status = MembershipStatus.ACTIVE
        else:
            status = MembershipStatus.PENDING

        membership = Membership(
            user_id=user.id,
            organization_id=tenant["organization_id"],
            role=data.role.value,
            status=status,
        )
        AuthRepository.create_membership(db, membership)

        _log(
            db,
            tenant["user_id"],
            "MEMBER_CREATED",
            f"{user.email} role={data.role.value}"
            + (" (existing account)" if account_exists else ""),
        )

        db.commit()
        db.refresh(membership)

        if temp_password:
            org = db.get(Organization, tenant["organization_id"])
            inviter = db.get(User, tenant["user_id"])
            rendered = member_invitation_email(
                full_name=user.full_name,
                email=user.email,
                temp_password=temp_password,
                organization_name=org.name if org else "your team",
                inviter_name=inviter.full_name if inviter else None,
            )
            send_email_async(
                to=user.email,
                subject=rendered.subject,
                text_body=rendered.text,
                html_body=rendered.html,
            )

        return {
            "member": _serialize(membership, user),
            "temp_password": temp_password,
            "account_exists": account_exists,
            "email_sent": bool(temp_password),
        }

    @staticmethod
    def update_role(
        db: Session, tenant, membership_id: str, new_role: Role
    ) -> dict:
        """Change a member's role.

        Permission model (OWNER/ADMIN gate is enforced by the router):
        - You cannot change your own role (prevents self-lockout).
        - Only an OWNER can promote another member to OWNER (ownership
          transfer should go through the dedicated transfer flow).
        - The last remaining OWNER cannot be demoted.
        - Otherwise OWNER and ADMIN may freely re-rank anyone, including
          other Admins and Owners.
        """
        row = MembersRepository.get_membership_with_user(
            db, membership_id, tenant["organization_id"]
        )
        if row is None:
            raise HTTPException(404, "Member not found")
        membership, user = row

        actor_role = tenant["role"]
        target_role = _role_str(membership.role)
        new_role_value = new_role.value

        if str(membership.user_id) == tenant["user_id"]:
            raise HTTPException(400, "You cannot change your own role")

        if target_role == new_role_value:
            return _serialize(membership, user)

        if new_role == Role.OWNER and actor_role != Role.OWNER.value:
            raise HTTPException(
                403, "Only an Owner can promote another member to Owner"
            )

        if (
            target_role == Role.OWNER.value
            and new_role != Role.OWNER
            and MembersRepository.count_owners(db, tenant["organization_id"]) <= 1
        ):
            raise HTTPException(400, "Cannot demote the last Owner of the organization")

        membership.role = new_role_value

        _log(
            db,
            tenant["user_id"],
            "MEMBER_ROLE_UPDATED",
            f"{user.email}: {target_role} -> {new_role_value}",
        )
        db.commit()
        db.refresh(membership)
        return _serialize(membership, user)

    @staticmethod
    def reset_password(db: Session, tenant, membership_id: str) -> dict:
        """Generate a fresh temp password, hash + persist it, and email the member.

        Permission model:
        - Cannot reset your own password through this admin endpoint.
        - Only an OWNER can reset another OWNER's password.
        """
        row = MembersRepository.get_membership_with_user(
            db, membership_id, tenant["organization_id"]
        )
        if row is None:
            raise HTTPException(404, "Member not found")
        membership, user = row

        if str(membership.user_id) == tenant["user_id"]:
            raise HTTPException(
                400, "Use account settings to change your own password"
            )

        target_role = _role_str(membership.role)
        if target_role == Role.OWNER.value and tenant["role"] != Role.OWNER.value:
            raise HTTPException(403, "Only an Owner can reset another Owner's password")

        temp_password = _gen_temp_password()
        user.password_hash = hash_password(temp_password)
        membership.status = MembershipStatus.PENDING

        _log(
            db,
            tenant["user_id"],
            "MEMBER_PASSWORD_RESET",
            user.email,
        )
        db.commit()

        rendered = password_reset_email(
            full_name=user.full_name,
            email=user.email,
            temp_password=temp_password,
        )
        send_email_async(
            to=user.email,
            subject=rendered.subject,
            text_body=rendered.text,
            html_body=rendered.html,
        )

        return {"temp_password": temp_password, "email_sent": True}

    @staticmethod
    def remove(db: Session, tenant, membership_id: str) -> dict:
        """Hard-delete a membership.

        Permission model:
        - Cannot remove yourself.
        - Only an OWNER can remove another OWNER, and the last OWNER cannot
          be removed (transfer ownership first).
        - If the removed user has no remaining memberships anywhere, their
          user record is hard-deleted too.
        """
        row = MembersRepository.get_membership_with_user(
            db, membership_id, tenant["organization_id"]
        )
        if row is None:
            raise HTTPException(404, "Member not found")
        membership, user = row

        target_role = _role_str(membership.role)
        target_email = user.email
        target_name = user.full_name

        if str(membership.user_id) == tenant["user_id"]:
            raise HTTPException(400, "You cannot remove yourself")

        if target_role == Role.OWNER.value:
            if tenant["role"] != Role.OWNER.value:
                raise HTTPException(403, "Only an Owner can remove another Owner")
            if MembersRepository.count_owners(db, tenant["organization_id"]) <= 1:
                raise HTTPException(
                    400,
                    "Cannot remove the last Owner. Transfer ownership first.",
                )

        org = db.get(Organization, tenant["organization_id"])
        actor = db.get(User, tenant["user_id"])
        org_name = org.name if org else "your team"
        actor_name = actor.full_name if actor else None

        user_id = membership.user_id

        db.delete(membership)
        db.flush()

        user_deleted = False
        if MembersRepository.count_user_memberships(db, user_id) == 0:
            orphan = db.get(User, user_id)
            if orphan is not None:
                # Detach FK-referencing rows before deleting the user so
                # foreign-key constraints don't block the cascade.
                from modules.auth.audit_model import AuditLog as _AuditLog
                from modules.auth.session_model import Session as _SessionRow

                db.query(_SessionRow).filter(
                    _SessionRow.user_id == user_id
                ).delete(synchronize_session=False)
                db.query(_AuditLog).filter(
                    _AuditLog.user_id == user_id
                ).update({_AuditLog.user_id: None}, synchronize_session=False)
                db.delete(orphan)
                user_deleted = True

        _log(
            db,
            tenant["user_id"],
            "MEMBER_REMOVED",
            f"{target_email} role={target_role}"
            + (" (user deleted)" if user_deleted else ""),
        )
        db.commit()

        rendered = member_removed_email(
            full_name=target_name,
            organization_name=org_name,
            actor_name=actor_name,
        )
        send_email_async(
            to=target_email,
            subject=rendered.subject,
            text_body=rendered.text,
            html_body=rendered.html,
        )

        return {
            "removed": True,
            "user_deleted": user_deleted,
            "email_sent": True,
        }
