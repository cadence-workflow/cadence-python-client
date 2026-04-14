from datetime import timedelta

from cadence import Registry, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()


@registry.workflow()
class SignalWaitWorkflow:
    def __init__(self) -> None:
        self.received: list[str] = []

    @workflow.run
    async def run(self, expected_count: int) -> str:
        await workflow.wait_condition(lambda: len(self.received) >= expected_count)
        return ",".join(self.received)

    @workflow.signal(name="append")
    def append(self, value: str):
        self.received.append(value)


async def _wait_for_close_event(
    helper: CadenceHelper, execution
) -> GetWorkflowExecutionHistoryResponse:
    async with helper.client() as client:
        return await client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )


async def _get_full_history(
    helper: CadenceHelper, execution
) -> GetWorkflowExecutionHistoryResponse:
    async with helper.client() as client:
        return await client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                skip_archival=True,
            )
        )


async def test_signal_workflow_unblocks_waiting_workflow(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "SignalWaitWorkflow",
            1,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "append",
            "hello",
        )

        response = await _wait_for_close_event(helper, execution)
        assert (
            '"hello"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


async def test_signal_with_start_workflow_delivers_initial_signal(
    helper: CadenceHelper,
):
    async with helper.worker(registry) as worker:
        execution = await worker.client.signal_with_start_workflow(
            "SignalWaitWorkflow",
            "append",
            ["same-batch"],
            1,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        response = await _wait_for_close_event(helper, execution)
        assert (
            '"same-batch"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


async def test_multiple_signals_preserve_history_order(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "SignalWaitWorkflow",
            3,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        for value in ("first", "second", "third"):
            await worker.client.signal_workflow(
                execution.workflow_id,
                execution.run_id,
                "append",
                value,
            )

        response = await _wait_for_close_event(helper, execution)
        assert (
            '"first,second,third"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )

        history = await _get_full_history(helper, execution)
        signal_events = [
            event.workflow_execution_signaled_event_attributes.signal_name
            for event in history.history.events
            if event.HasField("workflow_execution_signaled_event_attributes")
        ]
        assert signal_events == ["append", "append", "append"]
