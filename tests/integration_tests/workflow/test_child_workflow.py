import uuid
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


@reg.workflow()
class ParentStartsChildWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        run_id = WorkflowContext.get().info().workflow_run_id
        child_workflow_id = f"{run_id}-start-child-echo"
        handle = await workflow.start_child_workflow(
            "ChildEchoWorkflow",
            str,
            message,
            workflow_id=child_workflow_id,
            execution_start_to_close_timeout=timedelta(seconds=30),
            task_start_to_close_timeout=timedelta(seconds=10),
        )
        assert handle.workflow_id == child_workflow_id
        assert handle.run_id != ""
        return await handle


@reg.workflow()
class ChildWaitsForSignalWorkflow:
    """Child blocks until it receives ``append``; used for in-workflow signal APIs."""

    def __init__(self) -> None:
        self.received: list[str] = []

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: len(self.received) >= 1)
        return ",".join(self.received)

    @workflow.signal(name="append")
    def append(self, value: str) -> None:
        self.received.append(value)


@reg.workflow()
class ParentSignalsChildViaHandle:
    @workflow.run
    async def run(self) -> str:
        run_id = WorkflowContext.get().info().workflow_run_id
        child_workflow_id = f"{run_id}-child-signal-via-handle"
        handle = await workflow.start_child_workflow(
            "ChildWaitsForSignalWorkflow",
            str,
            workflow_id=child_workflow_id,
            execution_start_to_close_timeout=timedelta(seconds=30),
            task_start_to_close_timeout=timedelta(seconds=10),
        )
        await handle.signal("append", "from-parent-handle")
        return await handle


@reg.workflow()
class ParentSignalsExternalByWorkflowId:
    """Signals another open execution by workflow ID (``signal_external_workflow``)."""

    @workflow.run
    async def run(self, target_workflow_id: str) -> str:
        await workflow.signal_external_workflow(
            target_workflow_id, "append", "from-external-decision"
        )
        return "sent"


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


async def test_start_child_workflow_end_to_end(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "ParentStartsChildWorkflow",
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


async def test_child_workflow_future_signal_end_to_end(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "ParentSignalsChildViaHandle",
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
            '"from-parent-handle"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


async def test_signal_external_workflow_end_to_end(helper: CadenceHelper):
    target_workflow_id = f"ext-signal-target-{uuid.uuid4().hex}"
    async with helper.worker(reg) as worker:
        target_exec = await worker.client.start_workflow(
            "ChildWaitsForSignalWorkflow",
            task_list=worker.task_list,
            workflow_id=target_workflow_id,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        sender_exec = await worker.client.start_workflow(
            "ParentSignalsExternalByWorkflowId",
            target_workflow_id,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        target_response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=target_exec,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )
        assert (
            '"from-external-decision"'
            == target_response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )

        sender_response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=sender_exec,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )
        assert (
            '"sent"'
            == sender_response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )
