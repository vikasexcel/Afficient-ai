from modules.campaign.model import (Campaign)
from modules.campaign.repository import (CampaignRepository)
from modules.campaign.workflow_model import (Workflow)
from modules.campaign.repository import (WorkflowRepository)
from modules.campaign.execution_model import (Execution)
from modules.campaign.repository import (ExecutionRepository)
from modules.campaign.worker import (run_execution)
class CampaignService:

    @staticmethod
    def create(db,tenant,data,):
        campaign = Campaign(
            organization_id=tenant["organization_id"],
            name=data.name,
        )

        CampaignRepository.create(db,campaign,)
        db.commit()
        return {
            "id":campaign.id,
            "status":campaign.status,
        }

    
    @staticmethod
    def activate(db,campaign,):
        existing = (
            db.query(Workflow).filter(Workflow.campaign_id == campaign.id)
            .filter(Workflow.state == "active").first()
        )

        if existing:
            return {"error":"already active"}

        workflow = Workflow(
            campaign_id=campaign.id,
            state="active",
        )
        WorkflowRepository.create(db,workflow,)
        campaign.status = "active"
        db.commit()
        return {
            "workflow_id":workflow.id,
            "state":workflow.state,
        }

    @staticmethod
    def execute(db,workflow_id,):
        execution = Execution(
            workflow_id=workflow_id,
            status="queued",
        )

        ExecutionRepository.create(db,execution,)
        db.commit()
        return {
            "execution_id":execution.id,
            "status":execution.status,
        }

    @staticmethod
    def execute(db,workflow_id,):
        execution = Execution(
            workflow_id=workflow_id,
            status="queued",
        )

        ExecutionRepository.create(db,execution,)
        db.commit()
        run_execution(db,execution,)

        return {
            "execution_id":execution.id,
            "status":execution.status,
        }






