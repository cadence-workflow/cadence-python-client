import asyncio
from datetime import timedelta
from typing import cast

from cadence import Registry, workflow
from cadence._internal.workflow.statemachine.marker_state_machine import (
    VERSION_MARKER_NAME,
    marker_context_id,
)
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from cadence.data_converter import DefaultDataConverter
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()
_CHANGE_ID = "server-versioning"


@registry.workflow()
class VersioningWorkflow:
    def __init__(self) -> None:
        self._released = False

    @workflow.signal(name="release")
    def release(self) -> None:
        self._released = True

    @workflow.run
    async def run(self) -> str:
        from_marker = workflow.get_version(_CHANGE_ID, 1, 2)
        await workflow.wait_condition(lambda: self._released)
        # Widening max_supported must not change an already recorded version.
        after_signal = workflow.get_version(_CHANGE_ID, 1, 3)
        return f"{from_marker}/{after_signal}"


async def _full_history(
    helper: CadenceHelper, execution: WorkflowExecution
) -> GetWorkflowExecutionHistoryResponse:
    async with helper.client() as client:
        return cast(
            GetWorkflowExecutionHistoryResponse,
            await client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=DOMAIN_NAME,
                    workflow_execution=execution,
                    skip_archival=True,
                )
            ),
        )


async def _wait_for_version_marker(
    helper: CadenceHelper, execution: WorkflowExecution
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10
    while loop.time() < deadline:
        history = await _full_history(helper, execution)
        if any(
            event.HasField("marker_recorded_event_attributes")
            and event.marker_recorded_event_attributes.marker_name
            == VERSION_MARKER_NAME
            for event in history.history.events
        ):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Version marker was not recorded before workflow release")


async def test_version_marker_is_recorded_and_replayed_by_cadence(
    helper: CadenceHelper,
) -> None:
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "VersioningWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )
        # This ensures release is handled in a later decision task. The worker
        # currently replays complete history for each task; when sticky caching
        # is introduced, this test must explicitly evict its cached workflow.
        await _wait_for_version_marker(helper, execution)

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "release",
        )
        response = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        assert response.history.events[-1].HasField(
            "workflow_execution_completed_event_attributes"
        )
        assert (
            response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
            == '"2/2"'
        )

        history = await _full_history(helper, execution)
        version_markers = [
            event.marker_recorded_event_attributes
            for event in history.history.events
            if event.HasField("marker_recorded_event_attributes")
            and event.marker_recorded_event_attributes.marker_name
            == VERSION_MARKER_NAME
        ]
        assert len(version_markers) == 1
        assert marker_context_id(version_markers[0]) == _CHANGE_ID
        assert DefaultDataConverter().from_data(version_markers[0].details, [int]) == [
            2
        ]
