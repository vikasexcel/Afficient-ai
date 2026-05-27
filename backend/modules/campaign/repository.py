from modules.campaign.workflow_model import (
    Workflow
)
from modules.campaign.execution_model import (
    Execution
)


class CampaignRepository:
    @staticmethod
    def create(db, campaign):
        db.add(campaign)
        db.flush()
        return campaign


class WorkflowRepository:
    @staticmethod
    def create(db, workflow: Workflow):
        db.add(workflow)
        db.flush()
        return workflow



class ExecutionRepository:
    @staticmethod
    def create(db,execution,):
        db.add(execution)
        db.flush()
        return execution


