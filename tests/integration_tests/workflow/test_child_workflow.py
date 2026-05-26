from datetime import timedelta


from cadence import Registry, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from cadence.workflow import WorkflowContext
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

reg = Registry()


@reg.workflow()
class ChildEchoWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        return f"child:{message}"


@reg.workflow()
class ParentRunsChildWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        run_id = WorkflowContext.get().info().workflow_run_id
        child_workflow_id = f"{run_id}-child-echo"
        return await workflow.execute_child_workflow(
            "ChildEchoWorkflow",
            str,
            message,
            workflow_id=child_workflow_id,
            execution_start_to_close_timeout=timedelta(seconds=30),
            task_start_to_close_timeout=timedelta(seconds=10),
        )


async def test_execute_child_workflow_end_to_end(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "ParentRunsChildWorkflow",
            "hello world",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
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

        assert (
            '"child:hello world"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )
