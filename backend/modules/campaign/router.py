import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.schema import ActivateCampaign, CreateCampaign
from modules.campaign.service import CampaignService
from modules.campaign.workflow_model import Workflow

router = APIRouter(
    prefix="/campaigns",
    tags=["campaigns"],
)


def _org_uuid(tenant: dict) -> uuid.UUID:
    return uuid.UUID(str(tenant["organization_id"]))


@router.post("")
async def create(
    data: CreateCampaign,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    return CampaignService.create(db, tenant, data)


@router.post("/activate")
async def activate(
    data: ActivateCampaign,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    org_id = _org_uuid(tenant)
    campaign = (
        db.query(Campaign)
        .filter(
            Campaign.id == data.campaign_id,
            Campaign.organization_id == org_id,
        )
        .first()
    )
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    return CampaignService.activate(db, campaign)


@router.post("/execute/{workflow_id}")
async def execute(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    org_id = _org_uuid(tenant)
    # Tenant-scope the workflow lookup via its parent campaign.
    workflow = (
        db.query(Workflow)
        .join(Campaign, Campaign.id == Workflow.campaign_id)
        .filter(
            Workflow.id == workflow_id,
            Campaign.organization_id == org_id,
        )
        .first()
    )
    if workflow is None:
        raise HTTPException(404, "workflow not found")

    return await CampaignService.execute(db, workflow)


@router.get("/executions/{id}")
async def status(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    org_id = _org_uuid(tenant)
    row = (
        db.query(Execution)
        .join(Workflow, Workflow.id == Execution.workflow_id)
        .join(Campaign, Campaign.id == Workflow.campaign_id)
        .filter(
            Execution.id == id,
            Campaign.organization_id == org_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "execution not found")
    return {
        "id": str(row.id),
        "workflow_id": str(row.workflow_id),
        "status": row.status,
        "output": row.output,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
