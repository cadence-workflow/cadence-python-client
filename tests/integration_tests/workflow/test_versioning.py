from datetime import timedelta
from typing import cast

from cadence import Registry, workflow
from cadence._internal.workflow.statemachine.marker_state_machine import (
    VERSION_MARKER_NAME,
)
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from cadence.workflow import DEFAULT_VERSION
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
        from_marker = workflow.get_version(_CHANGE_ID, DEFAULT_VERSION, 2)
        await workflow.wait_condition(lambda: self._released)
        after_signal = workflow.get_version(_CHANGE_ID, DEFAULT_VERSION, 3)
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


async def test_default_version_is_stable_without_recording_a_marker(
    helper: CadenceHelper,
) -> None:
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "VersioningWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

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
            == '"-1/-1"'
        )

        history = await _full_history(helper, execution)
        version_markers = [
            event.marker_recorded_event_attributes
            for event in history.history.events
            if event.HasField("marker_recorded_event_attributes")
            and event.marker_recorded_event_attributes.marker_name
            == VERSION_MARKER_NAME
        ]
        assert version_markers == []
