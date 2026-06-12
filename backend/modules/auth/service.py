import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import update
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

from common.email.mailer import send_email_async
from config.settings import settings


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

    @staticmethod
    def forgot_password(db: Session, data) -> dict:
        email = data.email.strip().lower()
        user = AuthRepository.get_user(db, email)

        # Always return the same response to prevent email enumeration.
        _SAFE_RESPONSE = {
            "message": "If that email is registered, a reset link has been sent."
        }

        if user is None:
            return _SAFE_RESPONSE

        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expires_at = datetime.utcnow() + timedelta(hours=1)
        db.commit()

        _base = settings.APP_LOGIN_URL
        if _base.endswith("/login"):
            _base = _base[: -len("/login")]
        _base = _base.rstrip("/")
        reset_url = f"{_base}/reset-password?token={token}"

        html_body = f"""
        <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#07070a;color:#e5e5e5;border-radius:12px">
          <h2 style="color:#ffffff;margin-bottom:8px">Reset your password</h2>
          <p style="color:#a3a3a3;font-size:14px">Hi {user.full_name},<br><br>
          Click the button below to reset your Aifficient password.
          This link expires in <strong>1 hour</strong>.</p>
          <a href="{reset_url}"
             style="display:inline-block;margin-top:24px;padding:12px 28px;background:#7c3aed;color:#ffffff;text-decoration:none;border-radius:8px;font-size:14px;font-weight:600">
            Reset Password
          </a>
          <p style="color:#525252;font-size:12px;margin-top:32px">
            If you didn't request a password reset, you can safely ignore this email.
            Your password will not change.
          </p>
        </div>
        """

        text_body = (
            f"Hi {user.full_name},\n\n"
            "Reset your Aifficient password by visiting the link below (expires in 1 hour):\n\n"
            f"{reset_url}\n\n"
            "If you didn't request this, ignore this email."
        )

        send_email_async(
            to=user.email,
            subject="Reset your Aifficient password",
            text_body=text_body,
            html_body=html_body,
        )

        AuthService.log_event(db, user.id, "FORGOT_PASSWORD", user.email)
        db.commit()

        return _SAFE_RESPONSE

    @staticmethod
    def reset_password(db: Session, data) -> dict:
        user = AuthRepository.get_user_by_reset_token(db, data.token)

        if user is None or user.reset_token_expires_at is None:
            raise HTTPException(400, "Invalid or expired reset link.")

        if datetime.utcnow() > user.reset_token_expires_at:
            raise HTTPException(400, "Reset link has expired. Please request a new one.")

        user.password_hash = hash_password(data.new_password)
        user.reset_token = None
        user.reset_token_expires_at = None

        # Revoke all active sessions so stale tokens can't be reused.
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id)
            .values(revoked=True)
        )

        AuthService.log_event(db, user.id, "RESET_PASSWORD", user.email)
        db.commit()

        return {"message": "Password reset successfully. You can now log in."}


# Pre-computed bcrypt hash of a fixed dummy password. We compare against
# this in the user-not-found branch of login() so response timing is
# indistinguishable from the wrong-password branch.
_DUMMY_BCRYPT_HASH = (
    "$2b$12$abcdefghijklmnopqrstuuVrI2HZ7Z9P6Z8a/jrCWfHQ.s3yJ4hxa"
)