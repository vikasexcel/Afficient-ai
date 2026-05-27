from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.auth.tenant import get_current_tenant
from modules.campaign.schema import (CreateCampaign,)
from modules.campaign.service import (CampaignService,)
from modules.campaign.schema import (ActivateCampaign)
from modules.campaign.model import (Campaign)
from modules.campaign.execution_model import (Execution)


router = APIRouter(
    prefix="/campaigns",
    tags=["campaigns"],
)


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
    campaign = (
        db.query(Campaign).filter(Campaign.id == data.campaign_id).first()
    )
    return (CampaignService.activate(db,campaign,))


@router.post("/execute/{workflow_id}")
async def execute(
    workflow_id:str,
    db:Session = Depends(get_db),
):
    return (CampaignService.execute(db,workflow_id,))


@router.get( "/executions/{id}")
async def status(
    id:str,
    db:Session = Depends(get_db),
):
    execution = (db.query(Execution).filter(Execution.id == id).first()
    )

    return {
        "status":execution.status
    }