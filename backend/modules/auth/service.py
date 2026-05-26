from sqlalchemy.orm import Session
from modules.auth.model import User
from modules.auth.membership_model import Membership
from modules.auth.repository import AuthRepository
from common.security.password import hash_password
from common.security.jwt import create_token
from common.security.password import (
    verify_password,
)

class AuthService:

    @staticmethod
    def register(db: Session,data,):

        org = AuthRepository.create_organization(db,data.organization,)

        user = User(
            full_name=data.full_name,
            email=data.email,
            password_hash=hash_password(data.password),
        )

        user = AuthRepository.create_user(db,user,)

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role="owner",
        )

        AuthRepository.create_membership(db,membership,)

        db.commit()

        return {
            "message": "registered"
        }


    @staticmethod
    def login(db,data,):

        user = (
            AuthRepository.get_user(db,data.email,))

        if (not user):
            return {"error":"invalid"}

        valid = (
            verify_password(
                data.password,
                user.password_hash,
            )
        )

        if not valid:
            return {
                "error":"invalid"
            }

        token = (create_token(str(user.id)))

        return {
            "access_token":
            token
        }