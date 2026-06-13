"""Campaign lifecycle orchestration.

``CampaignService`` is responsible for campaign-level concerns only:

* CRUD lifecycle (create / read / update / delete).
* Activation — scheduling checks, workflow creation, lead enqueuing.
* Pause / resume — campaign + workflow state transitions.
* Voicemail / AMD configuration.
* Metrics orchestration (delegates to ``CampaignScheduler``).

Workflow-specific logic lives in :class:`~modules.campaign.workflow_service.WorkflowService`.
Execution-specific logic lives in :class:`~modules.campaign.execution_service.ExecutionService`.
Data access lives in :mod:`modules.campaign.repository`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from common.logging import get_logger
from modules.campaign.execution_service import ExecutionService
from modules.campaign.model import (
    CAMPAIGN_STATUS_ACTIVE,
    CAMPAIGN_STATUS_DRAFT,
    CAMPAIGN_STATUS_PAUSED,
    CAMPAIGN_STATUS_SCHEDULED,
    Campaign,
)
from modules.campaign.repository import CampaignRepository, ExecutionRepository
from modules.campaign.schema import (
    CampaignOut,
    CreateCampaign,
    UpdateCampaign,
    is_valid_status,
)
from modules.campaign.scheduling import (
    compute_scheduled_at,
    is_within_business_hours,
)
from modules.campaign.workflow_model import Workflow
from modules.campaign.workflow_service import WorkflowService
from modules.campaign.worker import run_execution

log = get_logger("campaign.service")

# Hard cap on how many leads a single activation will enqueue, protecting the
# request from runaway lists. Larger lists should move to a batch worker.
MAX_LEADS_PER_ACTIVATION = 1000


class CampaignService:

    # ------------------------------------------------------------------ #
    # Create
    # ------------------------------------------------------------------ #

    @staticmethod
    def create(db: Session, tenant: dict, data: CreateCampaign) -> dict:
        org_id = uuid.UUID(str(tenant["organization_id"]))

        scheduled_at = None
        timezone = None
        if data.schedule is not None:
            scheduled_at = compute_scheduled_at(
                start_immediately=data.schedule.start_immediately,
                date=data.schedule.date,
                time_str=data.schedule.time,
                tz_name=data.schedule.timezone,
            )
            timezone = data.schedule.timezone

        status = CAMPAIGN_STATUS_DRAFT
        if data.launch:
            status = (
                CAMPAIGN_STATUS_SCHEDULED
                if scheduled_at is not None
                else CAMPAIGN_STATUS_ACTIVE
            )

        campaign = Campaign(
            organization_id=org_id,
            name=data.name.strip(),
            status=status,
            playbook_id=data.playbook_id,
            lead_list_id=data.lead_list_id,
            scheduled_at=scheduled_at,
            timezone=timezone,
            business_hours=(
                data.business_hours.model_dump()
                if data.business_hours is not None
                else None
            ),
            retry_config=(
                data.retry_config.model_dump()
                if data.retry_config is not None
                else None
            ),
            voicemail_config=(
                data.voicemail_config.model_dump()
                if data.voicemail_config is not None
                else None
            ),
            calls_per_hour=(
                data.pacing.calls_per_hour if data.pacing is not None else None
            ),
            max_concurrent_calls=(
                data.pacing.max_concurrent_calls
                if data.pacing is not None
                else None
            ),
        )
        CampaignRepository.create(db, campaign)
        db.commit()
        db.refresh(campaign)

        return {
            "id": str(campaign.id),
            "status": campaign.status,
        }

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    @staticmethod
    def list(
        db: Session,
        org_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[CampaignOut], int]:
        rows, total = CampaignRepository.list_by_org(
            db, org_id, status=status, limit=limit, offset=offset
        )
        return CampaignService._enrich(db, rows), total

    @staticmethod
    def get_one(
        db: Session, org_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> CampaignOut:
        campaign = CampaignRepository.get(db, org_id, campaign_id)
        if campaign is None:
            raise HTTPException(404, "campaign not found")
        return CampaignService._enrich(db, [campaign])[0]

    @staticmethod
    def _enrich(db: Session, rows: list[Campaign]) -> list[CampaignOut]:
        import uuid as _uuid
        playbook_ids = {r.playbook_id for r in rows if r.playbook_id}
        list_ids = {r.lead_list_id for r in rows if r.lead_list_id}
        campaign_ids = [r.id for r in rows]
        pb_names = CampaignRepository.playbook_names(db, playbook_ids)
        ll_info = CampaignRepository.lead_list_info(db, list_ids)
        outcome_counts = ExecutionRepository.bulk_outcome_counts(db, campaign_ids)

        out: list[CampaignOut] = []
        for r in rows:
            name, count = ll_info.get(r.lead_list_id, (None, None))
            oc = outcome_counts.get(r.id, {})
            out.append(
                CampaignOut(
                    id=r.id,
                    name=r.name,
                    status=r.status,
                    playbook_id=r.playbook_id,
                    lead_list_id=r.lead_list_id,
                    scheduled_at=r.scheduled_at,
                    timezone=r.timezone,
                    business_hours=r.business_hours,
                    retry_config=r.retry_config,
                    voicemail_config=r.voicemail_config,
                    calls_per_hour=r.calls_per_hour,
                    max_concurrent_calls=r.max_concurrent_calls,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    playbook_name=pb_names.get(r.playbook_id),
                    lead_list_name=name,
                    lead_count=count,
                    executions_completed=oc.get("completed", 0),
                    meetings_booked=oc.get("meetings_booked", 0),
                )
            )
        return out

    # ------------------------------------------------------------------ #
    # Update / delete
    # ------------------------------------------------------------------ #

    @staticmethod
    def update(
        db: Session,
        org_id: uuid.UUID,
        campaign_id: uuid.UUID,
        data: UpdateCampaign,
    ) -> CampaignOut:
        campaign = CampaignRepository.get(db, org_id, campaign_id)
        if campaign is None:
            raise HTTPException(404, "campaign not found")

        fields = data.model_dump(exclude_unset=True)

        if "name" in fields and fields["name"] is not None:
            campaign.name = fields["name"].strip()
        if "playbook_id" in fields:
            campaign.playbook_id = fields["playbook_id"]
        if "lead_list_id" in fields:
            campaign.lead_list_id = fields["lead_list_id"]
        if "schedule" in fields and data.schedule is not None:
            campaign.scheduled_at = compute_scheduled_at(
                start_immediately=data.schedule.start_immediately,
                date=data.schedule.date,
                time_str=data.schedule.time,
                tz_name=data.schedule.timezone,
            )
            campaign.timezone = data.schedule.timezone
        if "business_hours" in fields and data.business_hours is not None:
            campaign.business_hours = data.business_hours.model_dump()
        if "retry_config" in fields and data.retry_config is not None:
            campaign.retry_config = data.retry_config.model_dump()
        if "voicemail_config" in fields and data.voicemail_config is not None:
            campaign.voicemail_config = data.voicemail_config.model_dump()
        if "pacing" in fields and data.pacing is not None:
            campaign.calls_per_hour = data.pacing.calls_per_hour
            campaign.max_concurrent_calls = data.pacing.max_concurrent_calls
        if "status" in fields and fields["status"] is not None:
            if not is_valid_status(fields["status"]):
                raise HTTPException(400, f"invalid status '{fields['status']}'")
            campaign.status = fields["status"]

        db.commit()
        db.refresh(campaign)
        return CampaignService._enrich(db, [campaign])[0]

    @staticmethod
    def delete(
        db: Session, org_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> None:
        campaign = CampaignRepository.get(db, org_id, campaign_id)
        if campaign is None:
            raise HTTPException(404, "campaign not found")
        CampaignRepository.delete(db, campaign)
        db.commit()

    # ------------------------------------------------------------------ #
    # Voicemail recording management
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_voicemail(
        db: Session, org_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> dict:
        """Return the campaign's voicemail / AMD configuration."""

        campaign = CampaignRepository.get(db, org_id, campaign_id)
        if campaign is None:
            raise HTTPException(404, "campaign not found")
        cfg = campaign.voicemail_config or {}
        return {
            "campaign_id": str(campaign.id),
            "voicemail_enabled": bool(cfg.get("voicemail_enabled", False)),
            "voicemail_message_url": cfg.get("voicemail_message_url"),
            "retry_on_voicemail": bool(cfg.get("retry_on_voicemail", False)),
            "amd_unknown_fallback": cfg.get("amd_unknown_fallback", "human"),
        }

    @staticmethod
    def set_voicemail(
        db: Session,
        org_id: uuid.UUID,
        campaign_id: uuid.UUID,
        *,
        voicemail_enabled: bool,
        message_url: str | None,
        retry_on_voicemail: bool,
        amd_unknown_fallback: str,
    ) -> dict:
        """Persist the campaign's voicemail / AMD configuration.

        The caller (router) is responsible for validating + storing any
        uploaded recording and resolving it to ``message_url`` first.
        """

        campaign = CampaignRepository.get(db, org_id, campaign_id)
        if campaign is None:
            raise HTTPException(404, "campaign not found")

        if voicemail_enabled and not message_url:
            raise HTTPException(
                400,
                "voicemail_enabled requires a recording (upload a file or "
                "set voicemail_message_url)",
            )

        fallback = (amd_unknown_fallback or "human").strip().lower()
        if fallback not in ("human", "voicemail"):
            raise HTTPException(
                400, "amd_unknown_fallback must be 'human' or 'voicemail'"
            )

        campaign.voicemail_config = {
            "voicemail_enabled": bool(voicemail_enabled),
            "voicemail_message_url": message_url,
            "retry_on_voicemail": bool(retry_on_voicemail),
            "amd_unknown_fallback": fallback,
        }
        db.commit()
        db.refresh(campaign)
        log.info(
            "campaign.voicemail.configured",
            campaign_id=str(campaign.id),
            enabled=voicemail_enabled,
            retry_on_voicemail=retry_on_voicemail,
        )
        return CampaignService.get_voicemail(db, org_id, campaign_id)

    # ------------------------------------------------------------------ #
    # Activation (connects playbook + leads + scheduling)
    # ------------------------------------------------------------------ #

    @staticmethod
    def activate(db: Session, campaign: Campaign) -> dict:
        # Idempotency guard: reuse the live workflow when one already exists.
        # A DB-level partial unique index on (campaign_id) WHERE state='active'
        # enforces this at the storage layer; this check surfaces a clean
        # response rather than letting the IntegrityError bubble up.
        existing = WorkflowService.get_active_workflow(
            db, campaign.id, lock=True
        )
        if existing:
            log.warning(
                "campaign.activate.already_active",
                campaign_id=str(campaign.id),
                workflow_id=str(existing.id),
            )
            # The workflow was pre-created (e.g. by saveWorkflow during the
            # wizard) before the campaign was explicitly activated.  Ensure the
            # campaign status reflects the live workflow so the UI shows
            # "active" rather than staying on "draft".
            if campaign.status not in (
                CAMPAIGN_STATUS_ACTIVE,
                CAMPAIGN_STATUS_SCHEDULED,
            ):
                campaign.status = CAMPAIGN_STATUS_ACTIVE
                log.info(
                    "campaign.activate.status_promoted",
                    campaign_id=str(campaign.id),
                )

            # Enqueue leads if the workflow has none yet (wizard saves the
            # workflow before activate is called, so the normal enqueue path
            # below is never reached for wizard-created campaigns).
            existing_count = sum(
                ExecutionRepository.count_by_status(db, campaign.id).values()
            )
            enqueued = 0
            if existing_count == 0 and campaign.lead_list_id:
                enqueued = CampaignService._enqueue_leads(db, campaign, existing)
                log.info(
                    "campaign.activate.leads_enqueued_on_existing_workflow",
                    campaign_id=str(campaign.id),
                    enqueued=enqueued,
                )

            db.commit()
            return {
                "workflow_id": str(existing.id),
                "state": existing.state,
                "already_active": True,
                "enqueued_leads": enqueued,
            }

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1) Future schedule -> hold as "scheduled", don't dial yet.
        if campaign.scheduled_at is not None and campaign.scheduled_at > now:
            campaign.status = CAMPAIGN_STATUS_SCHEDULED
            db.commit()
            return {
                "workflow_id": None,
                "state": CAMPAIGN_STATUS_SCHEDULED,
                "scheduled": True,
                "scheduled_at": campaign.scheduled_at.isoformat(),
                "message": "Campaign scheduled; dialing starts at the set time.",
            }

        # 2) Outside the configured business-hours window -> wait for it.
        if not is_within_business_hours(
            campaign.business_hours, campaign.timezone, now
        ):
            campaign.status = CAMPAIGN_STATUS_SCHEDULED
            db.commit()
            return {
                "workflow_id": None,
                "state": CAMPAIGN_STATUS_SCHEDULED,
                "scheduled": True,
                "within_business_hours": False,
                "message": (
                    "Outside calling hours; dialing resumes inside the "
                    "configured business-hours window."
                ),
            }

        # 3) Start now: create the workflow and enqueue per-lead executions.
        workflow = WorkflowService.create_workflow(
            db, campaign_id=campaign.id, state="active"
        )
        campaign.status = CAMPAIGN_STATUS_ACTIVE

        enqueued = 0
        if campaign.lead_list_id:
            enqueued = CampaignService._enqueue_leads(db, campaign, workflow)

        db.commit()
        log.info(
            "campaign.activated",
            campaign_id=str(campaign.id),
            workflow_id=str(workflow.id),
            enqueued_leads=enqueued,
        )
        return {
            "workflow_id": str(workflow.id),
            "state": workflow.state,
            "enqueued_leads": enqueued,
        }

    @staticmethod
    def _enqueue_leads(
        db: Session, campaign: Campaign, workflow: Workflow
    ) -> int:
        """Create one queued :class:`Execution` per lead in the list.

        For legacy workflows (``workflow.nodes == []``) ``current_node_id``
        is ``None`` so the existing scheduler and worker handle them without
        changes.  For graph-based workflows the entry node id is resolved
        and stamped on each execution so the worker knows which node to run
        first.
        """
        leads = CampaignRepository.leads_for_list(
            db,
            campaign.organization_id,
            campaign.lead_list_id,
            limit=MAX_LEADS_PER_ACTIVATION,
        )

        entry_node_id: str | None = None
        if workflow.nodes:
            try:
                entry_node_id = WorkflowService.get_entry_node(workflow)["id"]
            except ValueError:
                log.warning(
                    "campaign.enqueue.no_entry_node",
                    workflow_id=str(workflow.id),
                    campaign_id=str(campaign.id),
                )

        count = 0
        for lead in leads:
            ExecutionService.create_execution(
                db,
                workflow_id=workflow.id,
                lead_id=lead.id,
                context={
                    "campaign_id": str(campaign.id),
                    "playbook_id": str(campaign.playbook_id),
                    "lead": {
                        "id": str(lead.id),
                        "name": " ".join(
                            filter(None, [lead.first_name, lead.last_name])
                        ),
                        "first_name": lead.first_name or "",
                        "last_name": lead.last_name or "",
                        "phone": lead.phone,
                        "company": lead.company or "",
                        "email": lead.email or "",
                        "job_title": lead.job_title or "",
                        "linkedin_url": lead.linkedin_url or "",
                    },
                },
                current_node_id=entry_node_id,
            )
            count += 1
        return count

    # ------------------------------------------------------------------ #
    # Execute a single queued execution
    # ------------------------------------------------------------------ #

    @staticmethod
    async def execute(db: Session, workflow: Workflow) -> dict:
        """Run the next queued execution for ``workflow``.

        Returns ``status="no_work"`` when no queued execution exists.
        """
        execution = ExecutionService.get_next_queued_execution(db, workflow.id)
        if execution is None:
            return {
                "execution_id": None,
                "status": "no_work",
                "output": None,
                "lead_id": None,
            }

        await run_execution(db, execution)

        return {
            "execution_id": str(execution.id),
            "status": execution.status,
            "output": execution.output,
            "lead_id": str(execution.lead_id) if execution.lead_id else None,
        }

    # ------------------------------------------------------------------ #
    # Pause / resume (manual status transitions honoured by the scheduler)
    # ------------------------------------------------------------------ #

    @staticmethod
    def pause(db: Session, campaign: Campaign) -> dict:
        """``active`` -> ``paused``. The scheduler skips paused campaigns."""

        if campaign.status != CAMPAIGN_STATUS_ACTIVE:
            raise HTTPException(
                400,
                f"can only pause an active campaign (status={campaign.status})",
            )
        campaign.status = CAMPAIGN_STATUS_PAUSED
        workflow = WorkflowService.get_active_workflow(db, campaign.id)
        if workflow is not None:
            WorkflowService.update_state(db, workflow, "paused")
        db.commit()
        log.info("campaign.paused", campaign_id=str(campaign.id))
        return {"campaign_id": str(campaign.id), "status": campaign.status}

    @staticmethod
    def resume(db: Session, campaign: Campaign) -> dict:
        """``paused`` -> ``active``. The next tick resumes paced dispatch."""

        if campaign.status != CAMPAIGN_STATUS_PAUSED:
            raise HTTPException(
                400,
                f"can only resume a paused campaign (status={campaign.status})",
            )
        campaign.status = CAMPAIGN_STATUS_ACTIVE
        workflow = WorkflowService.get_paused_workflow(db, campaign.id)
        if workflow is not None:
            WorkflowService.update_state(db, workflow, "active")
        db.commit()
        log.info("campaign.resumed", campaign_id=str(campaign.id))
        return {"campaign_id": str(campaign.id), "status": campaign.status}
