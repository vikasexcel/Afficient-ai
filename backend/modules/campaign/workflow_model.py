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


class Workflow(
    BaseModel,
):

    __tablename__ = "workflows"

    campaign_id: Mapped[
        uuid.UUID
    ] = mapped_column(
        ForeignKey(
            "campaigns.id"
        )
    )

    state: Mapped[
        str
    ] = mapped_column(
        String(50),
        default="draft",
    )