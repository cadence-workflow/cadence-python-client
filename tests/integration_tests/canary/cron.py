from cadence import Registry, activity, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import GetWorkflowExecutionHistoryRequest
from cadence.workflow import WorkflowContext

from tests.integration_tests.canary.constants import (
    ACTIVITY_TYPE_CRON,
    SANITY_WORKFLOW_TIMEOUT,
    WORKFLOW_TYPE_CRON,
    WORKFLOW_TYPE_SANITY,
)

cron_registry = Registry()


@cron_registry.activity(name=ACTIVITY_TYPE_CRON)
async def start_canary_job(workflow_type: str, task_list: str) -> None:
    client = activity.client()
    execution = await client.start_workflow(
        workflow_type,
        task_list=task_list,
        execution_start_to_close_timeout=SANITY_WORKFLOW_TIMEOUT,
    )
    response = await client.workflow_stub.GetWorkflowExecutionHistory(
        GetWorkflowExecutionHistoryRequest(
            domain=client.domain,
            workflow_execution=execution,
            wait_for_new_event=True,
            history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
            skip_archival=True,
        )
    )
    close_event = response.history.events[-1]
    if (
        close_event.WhichOneof("attributes")
        != "workflow_execution_completed_event_attributes"
    ):
        raise RuntimeError(f"{workflow_type} did not complete successfully")


@cron_registry.workflow(name=WORKFLOW_TYPE_CRON)
class CronWorkflow:
    @workflow.run
    async def run(self, workflow_type: str = WORKFLOW_TYPE_SANITY) -> None:
        task_list = WorkflowContext.get().info().workflow_task_list
        await workflow.execute_activity(
            ACTIVITY_TYPE_CRON,
            type(None),
            workflow_type,
            task_list,
            schedule_to_close_timeout=SANITY_WORKFLOW_TIMEOUT,
        )
