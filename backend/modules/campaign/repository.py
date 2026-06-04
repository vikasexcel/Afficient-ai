import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from modules.campaign.execution_model import Execution
from modules.campaign.model import Campaign
from modules.campaign.workflow_model import Workflow
from modules.leads.model import Lead, LeadList
from modules.playbook.model import Playbook


class CampaignRepository:
    @staticmethod
    def create(db, campaign):
        db.add(campaign)
        db.flush()
        return campaign

    @staticmethod
    def get(
        db: Session,
        organization_id: uuid.UUID,
        campaign_id: uuid.UUID,
    ) -> Campaign | None:
        stmt = select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.organization_id == organization_id,
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def list_by_org(
        db: Session,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[Campaign], int]:
        base = select(Campaign).where(
            Campaign.organization_id == organization_id
        )
        if status is not None:
            base = base.where(Campaign.status == status)

        total = db.execute(
            select(func.count()).select_from(base.subquery())
        ).scalar_one()

        stmt = (
            base.order_by(Campaign.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list(db.execute(stmt).scalars())
        return rows, int(total)

    @staticmethod
    def delete(db: Session, campaign: Campaign) -> None:
        # The campaign's child rows (workflows + their executions) use plain
        # FKs with no ON DELETE cascade, so deleting the campaign directly
        # raises an IntegrityError once it has been activated. Remove the
        # children first, deepest first, then the campaign itself.
        workflow_ids = [
            row[0]
            for row in db.execute(
                select(Workflow.id).where(
                    Workflow.campaign_id == campaign.id
                )
            ).all()
        ]
        if workflow_ids:
            db.execute(
                delete(Execution).where(
                    Execution.workflow_id.in_(workflow_ids)
                )
            )
            db.execute(
                delete(Workflow).where(Workflow.id.in_(workflow_ids))
            )
        db.delete(campaign)

    # ------------------------------------------------------------------ #
    # Enrichment helpers for the listing UI
    # ------------------------------------------------------------------ #

    @staticmethod
    def playbook_names(
        db: Session, ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        rows = db.execute(
            select(Playbook.id, Playbook.name).where(Playbook.id.in_(ids))
        ).all()
        return {r[0]: r[1] for r in rows}

    @staticmethod
    def lead_list_info(
        db: Session, ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[str, int]]:
        if not ids:
            return {}
        rows = db.execute(
            select(
                LeadList.id, LeadList.name, LeadList.lead_count
            ).where(LeadList.id.in_(ids))
        ).all()
        return {r[0]: (r[1], r[2]) for r in rows}

    @staticmethod
    def leads_for_list(
        db: Session,
        organization_id: uuid.UUID,
        lead_list_id: uuid.UUID,
        *,
        limit: int = 1000,
    ) -> list[Lead]:
        stmt = (
            select(Lead)
            .where(
                Lead.organization_id == organization_id,
                Lead.lead_list_id == lead_list_id,
            )
            .order_by(Lead.created_at.asc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars())


class WorkflowRepository:
    @staticmethod
    def create(db, workflow: Workflow):
        db.add(workflow)
        db.flush()
        return workflow


class ExecutionRepository:
    @staticmethod
    def create(db, execution):
        db.add(execution)
        db.flush()
        return execution
