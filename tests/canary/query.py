from typing import cast

from cadence import Registry, activity, workflow
from cadence.workflow import WorkflowContext

from tests.canary.constants import (
    ACTIVITY_TIMEOUT,
    ACTIVITY_TYPE_QUERY_ONE,
    ACTIVITY_TYPE_QUERY_TWO,
    WORKFLOW_TYPE_QUERY,
)

_QUERY_TYPE = "canary-query-status"
_STATUS_STARTED = "started"
_STATUS_CLOSE_TO_FINISHED = "close-to-finished"

query_registry = Registry()


async def _query_workflow_status(workflow_id: str, run_id: str) -> str:
    return cast(
        str,
        await activity.client().query_workflow(
            workflow_id,
            run_id,
            _QUERY_TYPE,
            result_type=str,
        ),
    )


@query_registry.activity(name=ACTIVITY_TYPE_QUERY_ONE)
async def query_status_one(workflow_id: str, run_id: str) -> str:
    return await _query_workflow_status(workflow_id, run_id)


@query_registry.activity(name=ACTIVITY_TYPE_QUERY_TWO)
async def query_status_two(workflow_id: str, run_id: str) -> str:
    return await _query_workflow_status(workflow_id, run_id)


@query_registry.workflow(name=WORKFLOW_TYPE_QUERY)
class QueryWorkflow:
    def __init__(self) -> None:
        self.status = _STATUS_STARTED

    @workflow.run
    async def run(self) -> None:
        info = WorkflowContext.get().info()
        first_status = await workflow.execute_activity(
            ACTIVITY_TYPE_QUERY_ONE,
            str,
            info.workflow_id,
            info.workflow_run_id,
            schedule_to_close_timeout=ACTIVITY_TIMEOUT,
        )
        if first_status != self.status:
            raise ValueError(
                f"expected query status {self.status!r}, got {first_status!r}"
            )

        self.status = _STATUS_CLOSE_TO_FINISHED
        second_status = await workflow.execute_activity(
            ACTIVITY_TYPE_QUERY_TWO,
            str,
            info.workflow_id,
            info.workflow_run_id,
            schedule_to_close_timeout=ACTIVITY_TIMEOUT,
        )
        if second_status != self.status:
            raise ValueError(
                f"expected query status {self.status!r}, got {second_status!r}"
            )

    @workflow.query(name=_QUERY_TYPE)
    def query_status(self) -> str:
        return self.status
