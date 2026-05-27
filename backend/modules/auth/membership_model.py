import uuid
from sqlalchemy import Enum as SAEnum, ForeignKey
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from database.base import BaseModel
from common.security.roles import Role
from common.security.status import MembershipStatus


def _enum_values(enum_cls):
    return [m.value for m in enum_cls]


class Membership(BaseModel):
    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id")
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id")
    )

    role: Mapped[Role] = mapped_column(
        SAEnum(
            Role,
            name="role",
            values_callable=_enum_values,
        ),
        default=Role.MEMBER,
    )

    status: Mapped[MembershipStatus] = mapped_column(
        SAEnum(
            MembershipStatus,
            name="membership_status",
            values_callable=_enum_values,
        ),
        default=MembershipStatus.ACTIVE,
        server_default=MembershipStatus.ACTIVE.value,
    )