import uuid

from sqlalchemy import String
from sqlalchemy import ForeignKey

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from database.base import BaseModel


class AuditLog(
    BaseModel,
):

    __tablename__ = "audit_logs"

    user_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        ForeignKey(
            "users.id"
        ),
        nullable=True,
    )

    action: Mapped[
        str
    ] = mapped_column(
        String(100)
    )

    details: Mapped[
        str
    ] = mapped_column(
        String(500)
    )