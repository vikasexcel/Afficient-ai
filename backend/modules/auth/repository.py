from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from modules.auth.model import User
from modules.auth.organization_model import Organization
from modules.auth.membership_model import Membership
from modules.auth.session_model import Session
from modules.auth.audit_model import AuditLog

class AuthRepository:

    @staticmethod
    def create_organization(db: DBSession, name: str):
        org = Organization(name=name)
        db.add(org)
        db.flush()
        return org

    @staticmethod
    def create_user(db: DBSession, user: User):
        db.add(user)
        db.flush()
        return user

    @staticmethod
    def create_membership(db: DBSession, membership: Membership):
        db.add(membership)
        db.flush()
        return membership

    @staticmethod
    def get_user(db: DBSession, email: str):
        normalized = (email or "").strip().lower()
        stmt = select(User).where(func.lower(User.email) == normalized)
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_user_by_id(db: DBSession, user_id):
        return db.get(User, user_id)

    @staticmethod
    def create_session(db: DBSession, session: Session):
        db.add(session)
        db.flush()
        return session

    @staticmethod
    def get_session(db: DBSession, refresh_token: str):
        stmt = select(Session).where(Session.refresh_token == refresh_token)
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def revoke_session(db,refresh_token,):
        session = (AuthRepository.get_session(db,refresh_token,))
        if not session:
            return None
        session.revoked = True
        db.flush()
        return session

    @staticmethod
    def get_user_by_reset_token(db: DBSession, token: str):
        stmt = select(User).where(User.reset_token == token)
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def create_audit(db,audit,):
        db.add(audit)
        db.flush()
        return audit