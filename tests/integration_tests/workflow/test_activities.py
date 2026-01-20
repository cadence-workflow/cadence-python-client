import asyncio
from datetime import timedelta
from typing import Protocol

from cadence import workflow, Registry, activity
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()


@registry.activity()
async def echo(message: str) -> str:
    return message


@registry.workflow()
class SingleActivity:
    @workflow.run
    async def run(self, message: str) -> str:
        echo_activity = echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        )

        return await echo_activity(message)


@registry.workflow()
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


@registry.workflow()
class ParallelActivities:
    @workflow.run
    async def run(self, message: str) -> str:
        first = echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("first")

        second = echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute(message)

        first_res, second_res = await asyncio.gather(first, second)

        return second_res


async def test_single_activity(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
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
    async with helper.worker(registry) as worker:
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
    async with helper.worker(registry) as worker:
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


class ActivityMethodExample:
    def __init__(self, result: str):
        self.result = result

    @activity.method
    async def thing(self) -> str:
        return self.result


@registry.workflow()
class WorkflowWithActivityMethod:
    @workflow.run
    async def run(self) -> str:
        return await ActivityMethodExample.thing.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute()


async def test_activity_method(helper: CadenceHelper):
    test_reg = Registry()
    test_reg.register_activities(ActivityMethodExample("expected"))
    async with helper.worker(registry + test_reg) as worker:
        execution = await worker.client.start_workflow(
            "WorkflowWithActivityMethod",
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
            '"expected"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


class ActivityInterfaceExample(Protocol):
    @activity.method
    async def other_thing(self) -> str: ...


class ActivityImplExample(ActivityInterfaceExample):
    def __init__(self, result: str):
        self.result = result

    @activity.override(ActivityInterfaceExample.other_thing)
    async def other_thing(self) -> str:
        return self.result


@registry.workflow()
class WorkflowWithActivityInterface:
    @workflow.run
    async def run(self) -> str:
        return await ActivityInterfaceExample.other_thing.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute()


async def test_activity_interface(helper: CadenceHelper):
    test_reg = Registry()
    test_reg.register_activities(ActivityImplExample("expected"))
    async with helper.worker(registry + test_reg) as worker:
        execution = await worker.client.start_workflow(
            "WorkflowWithActivityInterface",
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
            '"expected"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )
