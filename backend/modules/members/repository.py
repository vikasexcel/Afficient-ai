from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.auth.model import User
from modules.auth.membership_model import Membership


class MembersRepository:
    @staticmethod
    def list_by_org(db: Session, organization_id: str):
        stmt = (
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at.asc())
        )
        return db.execute(stmt).all()

    @staticmethod
    def get_membership(db: Session, membership_id: str, organization_id: str):
        stmt = (
            select(Membership)
            .where(Membership.id == membership_id)
            .where(Membership.organization_id == organization_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_membership_with_user(
        db: Session, membership_id: str, organization_id: str
    ):
        stmt = (
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.id == membership_id)
            .where(Membership.organization_id == organization_id)
        )
        return db.execute(stmt).first()
