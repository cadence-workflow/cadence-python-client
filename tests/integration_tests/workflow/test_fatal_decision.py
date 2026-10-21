import asyncio
from datetime import timedelta

import pytest

from cadence import Registry, workflow
from cadence.client import Client
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.history_pb2 import HistoryEvent
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    TerminateWorkflowExecutionRequest,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()


def _incompatible_versions() -> None:
    # The first call records version 1, so the second call resolves to 1, which is
    # outside its supported range and raises a FatalDecisionError.
    workflow.get_version("change", 1, 1)
    workflow.get_version("change", 2, 2)


@registry.workflow()
class IncompatibleVersionWorkflow:
    @workflow.run
    async def run(self) -> str:
        _incompatible_versions()
        return "completed"


@registry.workflow()
class SwallowedFatalDecisionWorkflow:
    @workflow.run
    async def run(self) -> str:
        try:
            _incompatible_versions()
        except BaseException:
            pass
        return "swallowed"


async def _events_until_decision_task_failed(
    client: Client, execution: WorkflowExecution
) -> list[HistoryEvent]:
    """Long poll the history until the first DecisionTaskFailed event."""
    events: list[HistoryEvent] = []
    next_page_token = b""
    async with asyncio.timeout(10):
        while True:
            response = await client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=DOMAIN_NAME,
                    workflow_execution=execution,
                    next_page_token=next_page_token,
                    wait_for_new_event=True,
                    skip_archival=True,
                )
            )
            for event in response.history.events:
                events.append(event)
                if event.HasField("decision_task_failed_event_attributes"):
                    return events
            if not response.next_page_token:
                raise AssertionError("Workflow closed without failing a decision task")
            next_page_token = response.next_page_token


@pytest.mark.parametrize(
    "workflow_type",
    ["IncompatibleVersionWorkflow", "SwallowedFatalDecisionWorkflow"],
)
async def test_fatal_decision_error_fails_decision_task(
    helper: CadenceHelper, workflow_type: str
) -> None:
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            workflow_type,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        events = await _events_until_decision_task_failed(worker.client, execution)

        failed = events[-1].decision_task_failed_event_attributes
        assert b"outside the supported range" in failed.failure.details
        assert not any(
            event.HasField("decision_task_completed_event_attributes")
            or event.HasField("marker_recorded_event_attributes")
            or event.HasField("workflow_execution_completed_event_attributes")
            for event in events
        )

        await worker.client.workflow_stub.TerminateWorkflowExecution(
            TerminateWorkflowExecutionRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                reason="test complete",
            )
        )
