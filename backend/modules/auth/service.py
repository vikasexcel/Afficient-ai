from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from modules.auth.model import User
from modules.auth.membership_model import Membership
from modules.auth.session_model import Session as UserSession
from modules.auth.audit_model import AuditLog

from modules.auth.repository import AuthRepository

from common.security.roles import Role
from common.security.status import MembershipStatus
from common.security.password import (
    hash_password,
    verify_password,
)

from common.security.jwt import (
    create_token,
    create_refresh_token,
    decode_token,
)


class AuthService:

    @staticmethod
    def log_event(
        db,
        user_id,
        action,
        details,
    ):

        AuthRepository.create_audit(
            db,
            AuditLog(
                user_id=user_id,
                action=action,
                details=details,
            ),
        )

    @staticmethod
    def register(
        db: Session,
        data,
    ):

        org = AuthRepository.create_organization(
            db,
            data.organization,
        )

        user = User(
            full_name=data.full_name,
            email=data.email,
            password_hash=hash_password(
                data.password
            ),
        )

        user = AuthRepository.create_user(
            db,
            user,
        )

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=Role.OWNER,
            status=MembershipStatus.ACTIVE,
        )

        AuthRepository.create_membership(
            db,
            membership,
        )

        AuthService.log_event(
            db,
            user.id,
            "REGISTER",
            user.email,
        )

        db.commit()

        return {
            "message": "registered"
        }

    @staticmethod
    def login(
        db: Session,
        data,
    ):

        user = AuthRepository.get_user(
            db,
            data.email,
        )

        if not user:
            return {
                "error": "invalid"
            }

        valid = verify_password(
            data.password,
            user.password_hash,
        )

        if not valid:
            return {
                "error": "invalid"
            }

        access = create_token(
            str(user.id)
        )

        refresh = create_refresh_token(
            str(user.id)
        )

        AuthRepository.create_session(
            db,
            UserSession(
                user_id=user.id,
                refresh_token=refresh,
                expires_at=(
                    datetime.utcnow()
                    + timedelta(days=30)
                ),
            ),
        )

        AuthService.log_event(
            db,
            user.id,
            "LOGIN",
            user.email,
        )

        db.commit()

        return {
            "access_token": access,
            "refresh_token": refresh,
        }

    @staticmethod
    def refresh(
        db: Session,
        data,
    ):

        session = (
            AuthRepository
            .get_session(
                db,
                data.refresh_token,
            )
        )

        if not session:
            return {
                "error":
                "invalid session"
            }

        if session.revoked:
            return {
                "error":
                "revoked"
            }

        payload = decode_token(
            data.refresh_token
        )

        if not payload:
            return {
                "error":
                "expired"
            }

        access = create_token(
            payload["sub"]
        )

        AuthService.log_event(
            db,
            payload["sub"],
            "REFRESH",
            "token refreshed",
        )

        db.commit()

        return {
            "access_token": access
        }

    @staticmethod
    def logout(
        db: Session,
        data,
    ):

        session = (
            AuthRepository
            .revoke_session(
                db,
                data.refresh_token,
            )
        )

        if not session:

            return {
                "error":
                "session not found"
            }

        AuthService.log_event(
            db,
            session.user_id,
            "LOGOUT",
            "session revoked",
        )

        db.commit()

        return {
            "message":
            "logged out"
        }