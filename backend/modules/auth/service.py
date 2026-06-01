from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
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
        email = data.email.strip().lower()

        # Precheck so we can return a clean 409 instead of letting the
        # uniqueness constraint raise IntegrityError -> 500.
        existing = AuthRepository.get_user(db, email)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="email already registered",
            )

        try:
            org = AuthRepository.create_organization(
                db,
                data.organization,
            )

            user = User(
                full_name=data.full_name,
                email=email,
                password_hash=hash_password(data.password),
            )

            user = AuthRepository.create_user(db, user)

            membership = Membership(
                user_id=user.id,
                organization_id=org.id,
                role=Role.OWNER,
                status=MembershipStatus.ACTIVE,
            )

            AuthRepository.create_membership(db, membership)

            AuthService.log_event(
                db,
                user.id,
                "REGISTER",
                user.email,
            )

            db.commit()
        except IntegrityError:
            # Race condition: someone snuck in between the precheck and
            # the insert. Bubble up as 409 instead of 500.
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="email already registered",
            )

        return {
            "message": "registered",
            "user_id": str(user.id),
            "organization_id": str(org.id),
        }

    @staticmethod
    def login(
        db: Session,
        data,
    ):
        # Always do bcrypt work whether the user exists or not so the
        # response time doesn't leak email enumeration.
        user = AuthRepository.get_user(
            db,
            data.email.strip().lower(),
        )

        if user is None:
            # Burn comparable CPU against a dummy hash to keep timing
            # consistent with the wrong-password branch.
            verify_password(data.password, _DUMMY_BCRYPT_HASH)
            raise HTTPException(401, "invalid credentials")

        valid = verify_password(data.password, user.password_hash)
        if not valid:
            raise HTTPException(401, "invalid credentials")

        access = create_token(str(user.id))
        refresh = create_refresh_token(str(user.id))

        AuthRepository.create_session(
            db,
            UserSession(
                user_id=user.id,
                refresh_token=refresh,
                expires_at=(
                    datetime.utcnow() + timedelta(days=30)
                ),
            ),
        )

        AuthService.log_event(db, user.id, "LOGIN", user.email)

        db.commit()

        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
        }

    @staticmethod
    def refresh(
        db: Session,
        data,
    ):
        session = AuthRepository.get_session(db, data.refresh_token)

        if session is None:
            raise HTTPException(401, "invalid session")

        if session.revoked:
            raise HTTPException(401, "session revoked")

        payload = decode_token(data.refresh_token)
        if not payload:
            raise HTTPException(401, "session expired")

        access = create_token(payload["sub"])

        AuthService.log_event(
            db,
            payload["sub"],
            "REFRESH",
            "token refreshed",
        )

        db.commit()

        return {
            "access_token": access,
            "token_type": "bearer",
        }

    @staticmethod
    def logout(
        db: Session,
        data,
    ):
        session = AuthRepository.revoke_session(db, data.refresh_token)

        if session is None:
            # Idempotent: returning 204-style "ok" so a double-logout
            # from the SPA doesn't surface as an error to the user.
            return {"message": "logged out"}

        AuthService.log_event(
            db,
            session.user_id,
            "LOGOUT",
            "session revoked",
        )

        db.commit()

        return {"message": "logged out"}


# Pre-computed bcrypt hash of a fixed dummy password. We compare against
# this in the user-not-found branch of login() so response timing is
# indistinguishable from the wrong-password branch.
_DUMMY_BCRYPT_HASH = (
    "$2b$12$abcdefghijklmnopqrstuuVrI2HZ7Z9P6Z8a/jrCWfHQ.s3yJ4hxa"
)