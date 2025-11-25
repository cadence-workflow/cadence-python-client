import asyncio
from datetime import timedelta


from cadence import workflow, Registry
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

reg = Registry()


@reg.activity()
async def echo(message: str) -> str:
    return message


@reg.workflow()
class SingleActivity:
    @workflow.run
    async def run(self, message: str) -> str:
        return await echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute(message)


@reg.workflow()
class MultipleActivities:
    @workflow.run
    async def run(self, message: str) -> str:
        await echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("first")

        second = await echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute(message)

        await echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("third")

        return second


@reg.workflow()
class ParallelActivities:
    @workflow.run
    async def run(self, message: str) -> str:
        first = echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("first")

        second = echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute(message)

        first_res, second_res = await asyncio.gather(
            first, second, return_exceptions=True
        )

        return second_res


async def test_single_activity(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "SingleActivity",
            "hello world",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
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
            '"hello world"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


async def test_multiple_activities(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "MultipleActivities",
            "hello world",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
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
            '"hello world"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


async def test_parallel_activities(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "ParallelActivities",
            "hello world",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
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
            '"hello world"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )
