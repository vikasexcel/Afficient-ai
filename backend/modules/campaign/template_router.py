"""FastAPI router for workflow template APIs.

Endpoints
---------
GET  /workflow-templates
    List all workflow templates visible to the caller's organisation
    (system templates + org-owned templates).

GET  /workflow-templates/{template_id}
    Retrieve a single template by ID.

POST /workflow-templates/{template_id}/clone
    Clone a template (system or org-owned) into a new org-owned template.

Security
--------
* All endpoints require an authenticated tenant (JWT).
* ``GET`` endpoints are accessible to any authenticated user.
* ``POST /clone`` requires at least the AGENT role (same bar as campaign
  create / update).
* System templates (``is_system=True``) can be read and cloned but **never**
  deleted or modified via the API.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.auth.tenant import get_current_tenant
from modules.campaign.template_schema import (
    CloneTemplateRequest,
    WorkflowTemplateListResponse,
    WorkflowTemplateOut,
)
from modules.campaign.template_service import WorkflowTemplateService

router = APIRouter(
    prefix="/workflow-templates",
    tags=["workflow-templates"],
)


def _org_uuid(tenant: dict) -> uuid.UUID:
    return uuid.UUID(str(tenant["organization_id"]))


# ---------------------------------------------------------------------------
# GET /workflow-templates
# ---------------------------------------------------------------------------


@router.get("", response_model=WorkflowTemplateListResponse)
def list_templates(
    category: str | None = Query(default=None, description="Filter by category slug"),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_current_tenant),
):
    """Return all workflow templates visible to the caller's organisation.

    System templates (``is_system=true``) are listed first, then org-owned
    templates, both sorted by name.
    """
    org_id = _org_uuid(tenant)
    templates = WorkflowTemplateService.list_templates(
        db, org_id, category=category
    )
    return WorkflowTemplateListResponse(
        templates=[WorkflowTemplateOut.model_validate(t) for t in templates],
        total=len(templates),
    )


# ---------------------------------------------------------------------------
# GET /workflow-templates/{template_id}
# ---------------------------------------------------------------------------


@router.get("/{template_id}", response_model=WorkflowTemplateOut)
def get_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_current_tenant),
):
    """Retrieve a single workflow template by ID.

    Returns 404 when the template does not exist or is not accessible to the
    caller's organisation.
    """
    org_id = _org_uuid(tenant)
    template = WorkflowTemplateService.get_template(db, template_id, org_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return WorkflowTemplateOut.model_validate(template)


# ---------------------------------------------------------------------------
# POST /workflow-templates/{template_id}/clone
# ---------------------------------------------------------------------------


@router.post("/{template_id}/clone", response_model=WorkflowTemplateOut, status_code=201)
def clone_template(
    template_id: uuid.UUID,
    body: CloneTemplateRequest = CloneTemplateRequest(),
    db: Session = Depends(get_db),
    tenant: dict = Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    """Clone a template into a new org-owned copy.

    Both system templates and org-owned templates can be cloned.  The
    resulting template belongs to the caller's organisation and can be
    further customised.

    Returns 404 when *template_id* is not found or not visible to the caller.
    """
    org_id = _org_uuid(tenant)
    try:
        clone = WorkflowTemplateService.clone_template(
            db,
            template_id,
            org_id,
            name=body.name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    db.commit()
    db.refresh(clone)
    return WorkflowTemplateOut.model_validate(clone)
