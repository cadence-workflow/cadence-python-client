import asyncio
from datetime import timedelta

import cadence.workflow as workflow

from cadence import Registry
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

_TIMEOUT = timedelta(seconds=10)
_FAN_OUT = 13

reg = Registry()


@reg.activity(name="async_gather.produce")
def produce(count: int) -> list[int]:
    return list(range(count))


@reg.activity(name="async_gather.double")
def double(value: int) -> int:
    return value * 2


@reg.workflow(name="AsyncGatherWorkflow")
class AsyncGatherWorkflow:
    @workflow.run
    async def run(self, count: int) -> int:
        values = await workflow.execute_activity(
            "async_gather.produce",
            list[int],
            count,
            start_to_close_timeout=_TIMEOUT,
        )

        doubled = await asyncio.gather(
            *[
                workflow.execute_activity(
                    "async_gather.double",
                    int,
                    value,
                    start_to_close_timeout=_TIMEOUT,
                )
                for value in values
            ]
        )

        return sum(doubled)


async def test_asyncio_gather(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "AsyncGatherWorkflow",
            _FAN_OUT,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=100),
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

        expected = sum(value * 2 for value in range(_FAN_OUT))
        assert (
            str(expected)
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )

        all_history: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_ALL_EVENT,
                skip_archival=True,
            )
        )

        timed_out = [
            event
            for event in all_history.history.events
            if event.WhichOneof("attributes")
            == "decision_task_timed_out_event_attributes"
        ]
        assert not timed_out, f"Decision task(s) timed out: {timed_out}"
