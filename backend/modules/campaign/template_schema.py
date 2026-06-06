"""Pydantic schemas for the workflow-templates API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowTemplateOut(BaseModel):
    """Response shape for a single workflow template."""

    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    description: str | None
    category: str | None
    is_system: bool
    nodes: list[Any]
    edges: list[Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowTemplateListResponse(BaseModel):
    """Response shape for a list of workflow templates."""

    templates: list[WorkflowTemplateOut]
    total: int


class CloneTemplateRequest(BaseModel):
    """Optional body for ``POST /workflow-templates/{id}/clone``."""

    name: str | None = Field(
        default=None,
        description=(
            "Name for the cloned template. "
            "Defaults to 'Copy of <original name>'."
        ),
        max_length=255,
    )
