from typing import Optional

from pydantic import BaseModel, EmailStr

from common.security.roles import Role
from common.security.status import MembershipStatus


class MemberOut(BaseModel):
    membership_id: str
    user_id: str
    full_name: str
    email: EmailStr
    role: Role
    status: MembershipStatus


class CreateMemberInput(BaseModel):
    full_name: str
    email: EmailStr
    password: Optional[str] = None
    role: Role = Role.MEMBER


class CreateMemberOut(BaseModel):
    member: MemberOut
    temp_password: Optional[str] = None


class UpdateRoleInput(BaseModel):
    role: Role


class ResetPasswordOut(BaseModel):
    temp_password: str
