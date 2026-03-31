from datetime import timedelta

from cadence import Registry, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper


registry = Registry()


@registry.workflow()
class ContinueAsNewWorkflow:
    @workflow.run
    async def run(self, counter: int) -> str:
        if counter > 0:
            workflow.continue_as_new(counter - 1)
        return "done"


async def test_continue_as_new(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "ContinueAsNewWorkflow",
            1,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        # wait for close event
        await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=worker.client.domain,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        response: GetWorkflowExecutionHistoryResponse = (
            await worker.client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=worker.client.domain,
                    workflow_execution=execution,
                )
            )
        )

        events = response.history.events

        continued_as_new_events = [
            e
            for e in events
            if e.HasField("workflow_execution_continued_as_new_event_attributes")
        ]
        assert len(continued_as_new_events) == 1
