import uuid
from datetime import datetime
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy import DateTime

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from database.base import BaseModel


class Session(BaseModel):

    __tablename__ = "sessions"

    user_id: Mapped[
        uuid.UUID
    ] = mapped_column(
        ForeignKey(
            "users.id"
        )
    )

    refresh_token: Mapped[
        str
    ] = mapped_column(
        String(500),
        unique=True,
    )

    expires_at: Mapped[
        datetime
    ] = mapped_column(
        DateTime
    )

    revoked: Mapped[
        bool
    ] = mapped_column(
        default=False
    )