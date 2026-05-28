from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.security.roles import Role
from modules.auth.membership_model import Membership
from modules.auth.model import User


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

    @staticmethod
    def count_owners(db: Session, organization_id: str) -> int:
        stmt = (
            select(func.count(Membership.id))
            .where(Membership.organization_id == organization_id)
            .where(Membership.role == Role.OWNER)
        )
        return db.execute(stmt).scalar_one()

    @staticmethod
    def count_user_memberships(db: Session, user_id) -> int:
        stmt = select(func.count(Membership.id)).where(
            Membership.user_id == user_id
        )
        return db.execute(stmt).scalar_one()
