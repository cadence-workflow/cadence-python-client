import asyncio
from datetime import timedelta

from cadence import workflow, Registry, activity
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from cadence.api.v1.workflow_pb2 import TIMEOUT_TYPE_HEARTBEAT
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()


@registry.activity()
async def heartbeat_activity(iterations: int) -> str:
    for i in range(iterations):
        activity.heartbeat(i)
        await asyncio.sleep(0.75)
    return "done"


@registry.activity()
async def cancellable_heartbeat_activity() -> str:
    try:
        while True:
            activity.heartbeat("running")
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        raise


@registry.workflow()
class HeartbeatWorkflow:
    @workflow.run
    async def run(self, iterations: int) -> str:
        return await heartbeat_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=30),
            heartbeat_timeout=timedelta(seconds=2),
        ).execute(iterations)


@registry.workflow()
class ActivityCancellationWorkflow:
    @workflow.run
    async def run(self) -> str:
        activity_task = asyncio.create_task(
            cancellable_heartbeat_activity.with_options(
                schedule_to_close_timeout=timedelta(seconds=30),
                start_to_close_timeout=timedelta(seconds=30),
                heartbeat_timeout=timedelta(seconds=2),
            ).execute()
        )

        await workflow.sleep(timedelta(seconds=1))
        activity_task.cancel()

        try:
            await activity_task
        except asyncio.CancelledError:
            return "activity cancelled"

        return "activity completed"


@registry.activity()
async def no_heartbeat_activity(iterations: int) -> str:
    for _ in range(iterations):
        await asyncio.sleep(0.75)
    return "done"


@registry.workflow()
class NoHeartbeatWorkflow:
    @workflow.run
    async def run(self, iterations: int) -> str:
        return await no_heartbeat_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=30),
            heartbeat_timeout=timedelta(seconds=2),
        ).execute(iterations)


async def test_heartbeat_keeps_activity_alive(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "HeartbeatWorkflow",
            4,
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
            '"done"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


async def test_activity_without_heartbeat_times_out(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "NoHeartbeatWorkflow",
            4,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        # Wait for the workflow to close (activity timeout will cause workflow failure)
        await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        # Fetch the full history to verify the activity timed out due to missing heartbeat
        response: GetWorkflowExecutionHistoryResponse = (
            await worker.client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=DOMAIN_NAME,
                    workflow_execution=execution,
                    skip_archival=True,
                )
            )
        )

        timed_out_events = [
            event
            for event in response.history.events
            if event.HasField("activity_task_timed_out_event_attributes")
        ]
        assert timed_out_events
        assert (
            timed_out_events[-1].activity_task_timed_out_event_attributes.timeout_type
            == TIMEOUT_TYPE_HEARTBEAT
        )


async def test_activity_cancellation_is_delivered_by_heartbeat(
    helper: CadenceHelper,
):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "ActivityCancellationWorkflow",
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
            '"activity cancelled"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )

        response = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                skip_archival=True,
            )
        )

        canceled_events = [
            event
            for event in response.history.events
            if event.HasField("activity_task_canceled_event_attributes")
        ]
        assert canceled_events

        cancel_requested_events = [
            event
            for event in response.history.events
            if event.HasField("activity_task_cancel_requested_event_attributes")
        ]
        assert cancel_requested_events
