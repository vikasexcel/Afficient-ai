"""Business logic for campaigns, workflows, and executions.

Execution intentionally runs in-process (no Celery yet). The worker
talks to the AI module via :func:`run_execution` and returns a small
result dict the service persists on the row.
"""

from __future__ import annotations

from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.repository import (
    CampaignRepository,
    ExecutionRepository,
    WorkflowRepository,
)
from modules.campaign.workflow_model import Workflow
from modules.campaign.worker import run_execution


class CampaignService:

    @staticmethod
    def create(db, tenant, data):
        campaign = Campaign(
            organization_id=tenant["organization_id"],
            name=data.name,
        )
        CampaignRepository.create(db, campaign)
        db.commit()
        return {
            "id": str(campaign.id),
            "status": campaign.status,
        }

    @staticmethod
    def activate(db, campaign):
        existing = (
            db.query(Workflow)
            .filter(Workflow.campaign_id == campaign.id)
            .filter(Workflow.state == "active")
            .first()
        )
        if existing:
            return {
                "workflow_id": str(existing.id),
                "state": existing.state,
                "already_active": True,
            }

        workflow = Workflow(
            campaign_id=campaign.id,
            state="active",
        )
        WorkflowRepository.create(db, workflow)
        campaign.status = "active"
        db.commit()
        return {
            "workflow_id": str(workflow.id),
            "state": workflow.state,
        }

    @staticmethod
    async def execute(db, workflow):
        """Queue + run an execution for ``workflow``.

        The worker is fully async so the FastAPI event loop is not
        blocked by the LLM round-trip.
        """
        execution = Execution(
            workflow_id=workflow.id,
            status="queued",
        )
        ExecutionRepository.create(db, execution)
        db.commit()

        await run_execution(db, execution)

        return {
            "execution_id": str(execution.id),
            "status": execution.status,
            "output": execution.output,
        }
