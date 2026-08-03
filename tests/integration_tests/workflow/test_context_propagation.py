from contextvars import ContextVar
from datetime import timedelta

from typing import cast

import pytest

from cadence import ContextVarPropagator, Registry, workflow
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.history_pb2 import EventFilterType, HistoryEvent
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from cadence.worker import Worker
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

REQUEST_CONTEXT: ContextVar[str] = ContextVar("integration_request_context")
REQUEST_CONTEXT_PROPAGATOR = ContextVarPropagator(
    REQUEST_CONTEXT,
    "request-context",
    lambda value: value.encode(),
    bytes.decode,
)
registry = Registry()


@registry.activity()
async def read_request_context() -> str:
    return REQUEST_CONTEXT.get()


@registry.workflow()
class ContextPropagationWorkflow:
    """Reads context directly and via an activity, then continues as new once."""

    @workflow.run
    async def run(self, remaining_runs: int) -> str:
        activity_value = await read_request_context.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute()
        if remaining_runs > 0:
            workflow.continue_as_new(remaining_runs - 1)
        return f"{REQUEST_CONTEXT.get()}/{activity_value}"


async def _await_close_event(
    worker: Worker, execution: WorkflowExecution
) -> HistoryEvent:
    """Block until the given run closes and return its final history event."""
    response: GetWorkflowExecutionHistoryResponse = (
        await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )
    )
    return cast(HistoryEvent, response.history.events[-1])


async def test_context_propagates_through_activity_and_continue_as_new(
    helper: CadenceHelper,
) -> None:
    propagation_helper = CadenceHelper(
        {**helper.options, "context_propagators": (REQUEST_CONTEXT_PROPAGATOR,)},
        helper.test_name,
        helper.fspath,
    )
    async with propagation_helper.worker(registry) as worker:
        token = REQUEST_CONTEXT.set("integration-value")
        try:
            execution = await worker.client.start_workflow(
                "ContextPropagationWorkflow",
                1,
                task_list=worker.task_list,
                execution_start_to_close_timeout=timedelta(seconds=30),
            )
        finally:
            REQUEST_CONTEXT.reset(token)

        # First run: ends by continuing as new, carrying the context on the new run.
        first_run_close = await _await_close_event(worker, execution)
        continued = first_run_close.workflow_execution_continued_as_new_event_attributes
        assert continued.new_execution_run_id, (
            f"expected first run to continue as new, got {first_run_close}"
        )
        assert continued.header.fields["request-context"].data == b"integration-value"

        # Second run: sees the context only via the continue-as-new header, and
        # passes it on to its own activity.
        second_run_close = await _await_close_event(
            worker,
            WorkflowExecution(
                workflow_id=execution.workflow_id,
                run_id=continued.new_execution_run_id,
            ),
        )
        assert (
            second_run_close.workflow_execution_completed_event_attributes.result.data
            == b'"integration-value/integration-value"'
        )

    # The worker ran activities and decisions in this process; none of that may leak
    # context back into the caller's scope.
    with pytest.raises(LookupError):
        REQUEST_CONTEXT.get()
