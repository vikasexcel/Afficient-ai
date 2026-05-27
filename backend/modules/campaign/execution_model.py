import uuid
from sqlalchemy import (ForeignKey,String,)
from sqlalchemy.orm import (Mapped,mapped_column,)
from database.base import BaseModel
from sqlalchemy import Text

class Execution(
    BaseModel):
    __tablename__ = "executions"

    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"))
    status: Mapped[str] = mapped_column(String(50),default="queued",)
    output: Mapped[str | None] = mapped_column(Text,nullable=True,)