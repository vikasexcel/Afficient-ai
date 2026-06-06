import logging
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
from modules.campaign.model import Campaign
from modules.campaign.repository import (
    CampaignRepository,
    ExecutionRepository,
    WorkflowRepository,
)
from modules.campaign.schema import (
    ActivateCampaign,
    CampaignListResponse,
    CampaignMonitorPayload,
    CampaignOut,
    CreateCampaign,
    MonitorExecution,
    SchedulerStatusOut,
    UpdateCampaign,
    WorkflowGraphResponse,
    WorkflowGraphSchema,
    WorkflowRestoreResponse,
    WorkflowValidationResponse,
    WorkflowVersionDetail,
    WorkflowVersionListResponse,
    WorkflowVersionSummary,
)
from modules.campaign.scheduler import CampaignScheduler
from modules.campaign.scheduler_diagnostics import scheduler_status
from modules.campaign.service import CampaignService
from modules.campaign.workflow_service import WorkflowService
from modules.campaign.voicemail import (
    VoicemailValidationError,
    store_recording,
    validate_audio_format,
    validate_file_size,
    validate_voicemail_url,
)

router = APIRouter(
    prefix="/campaigns",
    tags=["campaigns"],
)

logger = logging.getLogger(__name__)


def _org_uuid(tenant: dict) -> uuid.UUID:
    return uuid.UUID(str(tenant["organization_id"]))


def _load_campaign(
    db: Session, org_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = CampaignRepository.get(db, org_id, campaign_id)
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


@router.get("/scheduler-status", response_model=SchedulerStatusOut)
async def get_scheduler_status(
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Report Celery worker / Beat / Redis health for campaign dispatch."""

    _ = tenant  # tenant-scoped auth; counts are global across the deployment
    return scheduler_status(db)


@router.post("/activate")
async def activate(
    data: ActivateCampaign,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    org_id = _org_uuid(tenant)
    campaign = CampaignRepository.get(db, org_id, data.campaign_id)
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
    workflow = WorkflowRepository.get_for_org(db, org_id, workflow_id)
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
    row = ExecutionRepository.get_for_org(db, org_id, id)
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
    row = ExecutionRepository.get_for_org(db, org_id, id)
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


@router.get("/{campaign_id}/monitor", response_model=CampaignMonitorPayload)
async def campaign_monitor(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Single-request dashboard payload for the Execution Monitoring UI.

    Returns campaign metadata, execution metrics, all executions with lead
    details (capped at 200, newest-first), and the active workflow graph.
    Avoids N+1 queries by joining executions with leads in one statement.
    """
    from modules.leads.model import Lead as LeadModel  # local import to avoid circular

    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
    metrics = CampaignScheduler.metrics(db, campaign)

    # Executions joined with leads — single query.
    rows = ExecutionRepository.list_for_campaign_with_leads(db, campaign_id)
    executions: list[MonitorExecution] = []
    for execution, lead in rows:
        lead_name: str | None = None
        lead_email: str | None = None
        lead_phone: str | None = None
        if lead is not None:
            parts = [p for p in [lead.first_name, lead.last_name] if p]
            lead_name = " ".join(parts) if parts else None
            lead_email = lead.email
            lead_phone = lead.phone
        executions.append(
            MonitorExecution(
                id=execution.id,
                status=execution.status,
                lead_id=execution.lead_id,
                lead_name=lead_name,
                lead_email=lead_email,
                lead_phone=lead_phone,
                current_node_id=execution.current_node_id,
                attempt_number=execution.attempt_number,
                outcome=execution.outcome,
                retry_status=execution.retry_status,
                next_retry_at=execution.next_retry_at,
                last_failure_reason=execution.last_failure_reason,
                node_outputs=execution.node_outputs,
                created_at=execution.created_at,
                updated_at=execution.updated_at,
            )
        )

    # Workflow graph (best-effort — 404 not raised for monitor).
    wf_nodes: list = []
    wf_edges: list = []
    try:
        wf = _load_active_workflow(db, campaign_id)
        wf_nodes = list(wf.nodes or [])
        wf_edges = list(wf.edges or [])
    except Exception:
        pass

    return CampaignMonitorPayload(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        campaign_status=campaign.status,
        campaign_created_at=campaign.created_at,
        lead_list_id=campaign.lead_list_id,
        metrics=metrics,
        executions=executions,
        workflow_nodes=wf_nodes,
        workflow_edges=wf_edges,
    )


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
# Workflow graph  (Phase 3A)
#
# Declared before the bare /{campaign_id} routes so the static "workflow"
# path segment is matched before the UUID catch-all.
# ---------------------------------------------------------------------------


def _load_active_workflow(db: Session, campaign_id: uuid.UUID):
    """Return the active workflow for *campaign_id*, falling back to the most
    recent workflow of any state (e.g. completed campaigns).  Raises 404 only
    when the campaign has no workflow at all."""
    wf = WorkflowRepository.get_active_for_campaign(db, campaign_id)
    if wf is None:
        wf = WorkflowRepository.get_latest_for_campaign(db, campaign_id)
    if wf is None:
        raise HTTPException(
            404,
            "no workflow for this campaign — use PUT /workflow to create one",
        )
    return wf


@router.get(
    "/{campaign_id}/workflow",
    response_model=WorkflowGraphResponse,
    summary="Get workflow graph",
)
async def get_workflow(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Return the active workflow graph for a campaign.

    Returns the ``nodes`` and ``edges`` arrays plus metadata.
    Responds 404 when the campaign has no active workflow (or the campaign
    itself does not exist / belongs to a different organisation).
    """
    try:
        campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
        wf = _load_active_workflow(db, campaign.id)
        logger.info(
            "Workflow GET: campaign_id=%s workflow_id=%s state=%s nodes=%d edges=%d",
            campaign_id, wf.id, wf.state,
            len(wf.nodes or []), len(wf.edges or []),
        )
        return WorkflowGraphResponse(
            workflow_id=wf.id,
            campaign_id=campaign.id,
            state=wf.state,
            nodes=list(wf.nodes or []),
            edges=list(wf.edges or []),
            node_count=len(wf.nodes or []),
            edge_count=len(wf.edges or []),
            is_graph=bool(wf.nodes),
            created_at=wf.created_at,
            updated_at=wf.updated_at,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Workflow GET failed: campaign_id=%s", campaign_id)
        raise


@router.put(
    "/{campaign_id}/workflow",
    response_model=WorkflowGraphResponse,
    summary="Replace workflow graph",
)
async def put_workflow(
    campaign_id: uuid.UUID,
    body: WorkflowGraphSchema,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    """Create or replace the workflow graph for a campaign.

    * If an active workflow already exists its graph is **replaced** in-place.
    * If there is no active workflow a new one is created with state
      ``"active"``.

    The request is rejected (422) when the graph fails validation.

    Not permitted for campaigns in ``completed`` status — those are archived.
    """
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)

    if campaign.status == "completed":
        raise HTTPException(
            409,
            "cannot update the workflow of a completed campaign",
        )

    nodes = body.to_nodes_list()
    edges = body.to_edges_list()

    # validate_workflow raises ValueError on the first error.
    try:
        WorkflowService.validate_workflow(nodes, edges)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    created_by = uuid.UUID(str(tenant["user_id"])) if tenant.get("user_id") else None
    wf = WorkflowRepository.get_active_for_campaign(db, campaign.id)
    if wf is not None:
        wf = WorkflowService.update_graph(
            db, wf, nodes=nodes, edges=edges, created_by=created_by
        )
    else:
        wf = WorkflowService.create_workflow(
            db,
            campaign_id=campaign.id,
            state="active",
            nodes=nodes,
            edges=edges,
            created_by=created_by,
        )
    db.commit()
    db.refresh(wf)

    return WorkflowGraphResponse(
        workflow_id=wf.id,
        campaign_id=campaign.id,
        state=wf.state,
        nodes=list(wf.nodes or []),
        edges=list(wf.edges or []),
        node_count=len(wf.nodes or []),
        edge_count=len(wf.edges or []),
        is_graph=bool(wf.nodes),
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


@router.post(
    "/{campaign_id}/workflow/validate",
    response_model=WorkflowValidationResponse,
    summary="Validate workflow graph",
)
async def validate_workflow(
    campaign_id: uuid.UUID,
    body: WorkflowGraphSchema,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    """Validate a workflow graph without persisting it.

    Returns all errors and warnings in a single response so the frontend can
    surface the complete set of issues at once rather than one-at-a-time.
    Always returns HTTP 200 — ``valid`` in the body indicates the result.
    """
    # Confirm campaign ownership (same tenant guard, no 404 leak).
    _load_campaign(db, _org_uuid(tenant), campaign_id)

    nodes = body.to_nodes_list()
    edges = body.to_edges_list()
    errors, warnings = WorkflowService.validate_graph_detailed(nodes, edges)

    return WorkflowValidationResponse(
        valid=not errors,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Workflow version history  (Phase 3C)
# ---------------------------------------------------------------------------


@router.get(
    "/{campaign_id}/workflow/versions",
    response_model=WorkflowVersionListResponse,
    summary="List workflow version history",
)
async def list_workflow_versions(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Return the version history for the campaign's active workflow.

    Versions are ordered newest-first.  Each entry includes the version number,
    creation timestamp, and the author UUID (if recorded).  Graph payloads are
    omitted for brevity — use GET /versions/{version} to fetch a snapshot.

    Returns 404 when the campaign has no active workflow.
    """
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
    wf = _load_active_workflow(db, campaign.id)
    versions = WorkflowService.list_versions(db, wf.id)
    return WorkflowVersionListResponse(
        workflow_id=wf.id,
        versions=[WorkflowVersionSummary.model_validate(v) for v in versions],
        total=len(versions),
    )


@router.get(
    "/{campaign_id}/workflow/versions/{version}",
    response_model=WorkflowVersionDetail,
    summary="Get a workflow version snapshot",
)
async def get_workflow_version(
    campaign_id: uuid.UUID,
    version: int,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Return the full graph snapshot (nodes + edges) for a specific version.

    Returns 404 when the campaign, workflow, or version number is not found.
    """
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)
    wf = _load_active_workflow(db, campaign.id)
    record = WorkflowService.get_version(db, wf.id, version)
    if record is None:
        raise HTTPException(
            404,
            f"version {version} not found for this workflow",
        )
    return WorkflowVersionDetail.model_validate(record)


@router.post(
    "/{campaign_id}/workflow/versions/{version}/restore",
    response_model=WorkflowRestoreResponse,
    summary="Restore a workflow version",
)
async def restore_workflow_version(
    campaign_id: uuid.UUID,
    version: int,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    """Restore the campaign's workflow graph to the state captured in *version*.

    A **new** version record is created with the restored content so the
    operation is fully auditable and history is never destroyed.

    Not permitted for campaigns in ``completed`` status.

    Returns 404 when the campaign, workflow, or requested version is missing.
    Returns 422 when the snapshot fails graph validation.
    """
    campaign = _load_campaign(db, _org_uuid(tenant), campaign_id)

    if campaign.status == "completed":
        raise HTTPException(
            409,
            "cannot restore a workflow version for a completed campaign",
        )

    wf = _load_active_workflow(db, campaign.id)
    created_by = uuid.UUID(str(tenant["user_id"])) if tenant.get("user_id") else None

    try:
        wf, new_ver = WorkflowService.restore_version(
            db, wf, version, created_by=created_by
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    db.commit()
    db.refresh(wf)

    return WorkflowRestoreResponse(
        workflow_id=wf.id,
        restored_from_version=version,
        new_version=new_ver.version,
        nodes=list(wf.nodes or []),
        edges=list(wf.edges or []),
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
