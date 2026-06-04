import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy.orm import Session

from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.auth.tenant import get_current_tenant
from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.schema import (
    ActivateCampaign,
    CampaignListResponse,
    CampaignOut,
    CreateCampaign,
    UpdateCampaign,
)
from modules.campaign.scheduler import CampaignScheduler
from modules.campaign.service import CampaignService
from modules.campaign.voicemail import (
    VoicemailValidationError,
    store_recording,
    validate_audio_format,
    validate_file_size,
    validate_voicemail_url,
)
from modules.campaign.workflow_model import Workflow

router = APIRouter(
    prefix="/campaigns",
    tags=["campaigns"],
)


def _org_uuid(tenant: dict) -> uuid.UUID:
    return uuid.UUID(str(tenant["organization_id"]))


def _load_campaign(
    db: Session, org_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = (
        db.query(Campaign)
        .filter(
            Campaign.id == campaign_id,
            Campaign.organization_id == org_id,
        )
        .first()
    )
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    return campaign


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


@router.post("")
async def create(
    data: CreateCampaign,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    return CampaignService.create(db, tenant, data)


@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    campaigns, total = CampaignService.list(
        db, _org_uuid(tenant), status=status, limit=limit, offset=offset
    )
    return CampaignListResponse(campaigns=campaigns, total=total)


# ---------------------------------------------------------------------------
# Lifecycle actions + executions
#
# These are declared *before* the dynamic ``/{campaign_id}`` routes so the
# static path segments ("activate", "execute", "executions") are matched
# first and never swallowed by the UUID path param.
# ---------------------------------------------------------------------------


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
        "lead_id": str(row.lead_id) if row.lead_id else None,
        "attempt_number": row.attempt_number,
        "outcome": row.outcome,
        "retry_status": row.retry_status,
        "next_retry_at": (
            row.next_retry_at.isoformat() if row.next_retry_at else None
        ),
        "last_failure_reason": row.last_failure_reason,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/executions/{id}/retry-history")
async def execution_retry_history(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
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
    return CampaignScheduler.retry_history(db, row)


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
    return CampaignService.pause(db, campaign)


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
    return CampaignService.resume(db, campaign)


@router.get("/{campaign_id}/schedule-status")
async def schedule_status(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
    return CampaignScheduler.schedule_status(db, campaign)


@router.get("/{campaign_id}/metrics")
async def campaign_metrics(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
    return CampaignScheduler.metrics(db, campaign)


@router.get("/{campaign_id}/retries")
async def campaign_retries(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
    return CampaignScheduler.retries(db, campaign)


# ---------------------------------------------------------------------------
# Voicemail recording management (AMD / Voicemail Drop)
# ---------------------------------------------------------------------------


@router.get("/{campaign_id}/voicemail")
async def get_voicemail(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Return the campaign's voicemail / AMD configuration."""

    return CampaignService.get_voicemail(db, _org_uuid(tenant), campaign_id)


@router.post("/{campaign_id}/voicemail")
async def set_voicemail(
    campaign_id: uuid.UUID,
    voicemail_enabled: bool = Form(True),
    retry_on_voicemail: bool = Form(False),
    amd_unknown_fallback: str = Form("human"),
    voicemail_message_url: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    """Upload or configure the campaign's voicemail-drop recording.

    Two ways to supply the recording (multipart form):

    * ``file`` — upload an audio file. Validated for format + size, stored,
      and the resulting URL becomes ``voicemail_message_url``.
    * ``voicemail_message_url`` — point at an externally hosted recording.
      Validated for shape (and accessibility when the network check is on).
    """

    org_id = _org_uuid(tenant)
    # Ensure the campaign exists + is tenant-scoped before doing any work.
    _load_campaign(db, org_id, campaign_id)

    resolved_url: str | None = None
    try:
        if file is not None and file.filename:
            fmt = validate_audio_format(
                filename=file.filename,
                content_type=file.content_type,
            )
            data = await file.read()
            validate_file_size(len(data))
            resolved_url = store_recording(
                campaign_id=str(campaign_id), data=data, fmt=fmt
            )
        elif voicemail_message_url:
            resolved_url = validate_voicemail_url(voicemail_message_url)
    except VoicemailValidationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc

    return CampaignService.set_voicemail(
        db,
        org_id,
        campaign_id,
        voicemail_enabled=voicemail_enabled,
        message_url=resolved_url,
        retry_on_voicemail=retry_on_voicemail,
        amd_unknown_fallback=amd_unknown_fallback,
    )


# ---------------------------------------------------------------------------
# Single campaign (dynamic id — declared last)
# ---------------------------------------------------------------------------


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    return CampaignService.get_one(db, _org_uuid(tenant), campaign_id)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID,
    data: UpdateCampaign,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    return CampaignService.update(db, _org_uuid(tenant), campaign_id, data)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    CampaignService.delete(db, _org_uuid(tenant), campaign_id)
