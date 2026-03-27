from datetime import timedelta

from cadence import Registry, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper


registry = Registry()


@registry.activity()
async def echo(message: str) -> str:
    return message


@registry.workflow()
class TimerWorkflow:
    @workflow.run
    async def run(self) -> str:
        await workflow.start_timer(timedelta(seconds=1))
        await echo("hello")
        return "hello"


async def test_timer(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "TimerWorkflow",
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

        timer_started_events = [
            e for e in events if e.HasField("timer_started_event_attributes")
        ]
        timer_fired_events = [
            e for e in events if e.HasField("timer_fired_event_attributes")
        ]
        assert len(timer_started_events) == 1
        assert len(timer_fired_events) == 1

        activity_scheduled_events = [
            e for e in events if e.HasField("activity_task_scheduled_event_attributes")
        ]
        assert len(activity_scheduled_events) == 1

        timer_started_time = timer_started_events[0].event_time.ToDatetime()
        activity_scheduled_time = activity_scheduled_events[0].event_time.ToDatetime()
        assert activity_scheduled_time >= timer_started_time + timedelta(seconds=1)
