import uuid

from sqlalchemy import (
    ForeignKey,
    String,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from database.base import BaseModel


class Campaign(
    BaseModel
):

    __tablename__ = "campaigns"

    organization_id: Mapped[
        uuid.UUID
    ] = mapped_column(
        ForeignKey(
            "organizations.id"
        )
    )

    name: Mapped[
        str
    ] = mapped_column(
        String(255)
    )

    status: Mapped[
        str
    ] = mapped_column(
        String(50),
        default="draft",
    )