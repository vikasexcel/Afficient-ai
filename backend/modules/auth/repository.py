from sqlalchemy.orm import Session

from modules.auth.model import User
from modules.auth.organization_model import Organization
from modules.auth.membership_model import Membership
from sqlalchemy import select


class AuthRepository:

    @staticmethod
    def create_organization(
        db: Session,
        name: str,
    ):
        org = Organization(
            name=name
        )

        db.add(org)

        db.flush()

        return org


    @staticmethod
    def create_user(
        db: Session,
        user: User,
    ):
        db.add(user)

        db.flush()

        return user


    @staticmethod
    def create_membership(
        db: Session,
        membership: Membership,
    ):
        db.add(
            membership
        )

        db.flush()

        return membership
    
    @staticmethod
    def get_user(
        db,
        email,
    ):

        stmt = (select(User).where(User.email== email))

        return (db.execute(stmt).scalar_one_or_none())