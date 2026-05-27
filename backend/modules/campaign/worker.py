from modules.ai.service import AIService
from modules.campaign.execution_model import Execution


def run_execution(
    db,
    execution: Execution,
):

    execution.status = "running"

    db.commit()

    result = AIService.execute(
        "Run campaign"
    )

    print(result)

    execution.output = result[
        "output"
    ]

    execution.status = (
        "completed"
    )

    db.commit()

    db.refresh(
        execution
    )

    return execution