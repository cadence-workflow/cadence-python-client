from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.canary import WORKFLOW_TYPE_SANITY, registry
from tests.canary.constants import SANITY_WORKFLOW_TIMEOUT
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME


async def test_sanity_workflow(helper: CadenceHelper) -> None:
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            WORKFLOW_TYPE_SANITY,
            task_list=worker.task_list,
            execution_start_to_close_timeout=SANITY_WORKFLOW_TIMEOUT,
        )

        response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        close_event = response.history.events[-1]
        assert (
            close_event.WhichOneof("attributes")
            == "workflow_execution_completed_event_attributes"
        )
