from datetime import timedelta
from typing import cast

from cadence import workflow, Registry, activity
from cadence.api.v1 import workflow_pb2
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()


class NonRetryable(Exception):
    """Named exception used for non_retryable_error_reasons matching.

    Cadence matches ``Failure.reason`` (the activity exception's class name) against
    the policy's ``non_retryable_error_reasons`` list to decide whether to retry.
    """


@registry.activity()
async def flaky(succeed_on_attempt: int) -> int:
    """Fails until ``ActivityInfo.attempt`` reaches ``succeed_on_attempt``.

    Cadence numbers the first attempt as ``0``, so ``succeed_on_attempt=2`` means the
    activity fails on attempts 0 and 1 and succeeds on attempt 2 (i.e. two retries).
    """
    current = activity.info().attempt
    if current < succeed_on_attempt:
        raise RuntimeError(f"flaky attempt {current} failing")
    return current


@registry.activity()
async def always_non_retryable() -> None:
    raise NonRetryable("do not retry me")


@registry.workflow()
class RetryActivityWorkflow:
    @workflow.run
    async def run(self, succeed_on_attempt: int) -> int:
        return await flaky.with_options(
            schedule_to_close_timeout=timedelta(seconds=60),
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy={
                "initial_interval": timedelta(seconds=1),
                "backoff_coefficient": 1.0,
                "maximum_interval": timedelta(seconds=1),
                "maximum_attempts": 5,
            },
        ).execute(succeed_on_attempt)


@registry.workflow()
class NoRetryActivityWorkflow:
    @workflow.run
    async def run(self) -> None:
        await always_non_retryable.with_options(
            schedule_to_close_timeout=timedelta(seconds=30),
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy={
                "initial_interval": timedelta(seconds=1),
                "backoff_coefficient": 1.0,
                "maximum_attempts": 5,
                "non_retryable_error_reasons": ["NonRetryable"],
            },
        ).execute()


async def test_activity_retries_until_success(helper: CadenceHelper):
    """With max_attempts=5 and an activity that succeeds on attempt 2, the workflow
    should complete and return 2, proving the server honored the retry policy."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "RetryActivityWorkflow",
            2,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=60),
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
            "2"
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


async def test_non_retryable_error_skips_retries(helper: CadenceHelper):
    """An error whose class name is listed in ``non_retryable_error_reasons`` should
    fail the activity after a single attempt even though max_attempts=5.

    We assert on the recorded ``ActivityTaskFailed.failure.reason`` (which must equal
    the exception class name so the server's non-retryable match works) and on the
    absence of an ``ActivityTaskCompleted`` event.
    """
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "NoRetryActivityWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        full_history: GetWorkflowExecutionHistoryResponse = (
            await worker.client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=DOMAIN_NAME,
                    workflow_execution=execution,
                    skip_archival=True,
                )
            )
        )

        failed_events = [
            event
            for event in full_history.history.events
            if event.HasField("activity_task_failed_event_attributes")
        ]
        assert failed_events, "expected an ActivityTaskFailed event"
        assert (
            failed_events[-1].activity_task_failed_event_attributes.failure.reason
            == "NonRetryable"
        )

        completed_events = [
            event
            for event in full_history.history.events
            if event.HasField("activity_task_completed_event_attributes")
        ]
        assert not completed_events, (
            "non-retryable error should not produce a successful completion"
        )


wf_retry_registry = Registry()


class AlwaysFailsError(Exception):
    """Always raised by the failing workflow."""


class NonRetryableWorkflowError(Exception):
    """Listed in non_retryable_error_reasons to block retries."""


@wf_retry_registry.workflow()
class AlwaysFailsWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise AlwaysFailsError("workflow always fails")


@wf_retry_registry.workflow()
class NonRetryableWorkflowErrorWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise NonRetryableWorkflowError("non-retryable")


async def _wait_for_close(
    helper: CadenceHelper,
    execution: WorkflowExecution,
) -> GetWorkflowExecutionHistoryResponse:
    """Block until the given run reaches a terminal (close) event.

    This is a server-side long-poll — the server holds the request open until
    a close event lands, so there is no client-side sleep or polling loop.
    """
    async with helper.client() as client:
        return cast(
            GetWorkflowExecutionHistoryResponse,
            await client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=DOMAIN_NAME,
                    workflow_execution=execution,
                    wait_for_new_event=True,
                    history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                    skip_archival=True,
                )
            ),
        )


async def test_workflow_retries_on_failure(helper: CadenceHelper):
    """Server retries the workflow when retry_policy is set and the run fails.

    With maximum_attempts=2 the first run fails and is continued-as-new with
    RETRY_POLICY initiator, and the second run also fails (terminal).  We verify
    the chain of runs in history.
    """
    async with helper.worker(wf_retry_registry) as worker:
        execution = await worker.client.start_workflow(
            "AlwaysFailsWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
            retry_policy={
                "initial_interval": timedelta(seconds=1),
                "backoff_coefficient": 1.0,
                "maximum_interval": timedelta(seconds=1),
                "maximum_attempts": 2,
            },
        )

        # Wait for the *first* run to close (ContinuedAsNew or Failed)
        first_close = await _wait_for_close(helper, execution)
        first_close_event = first_close.history.events[-1]

        # The first run must be continued-as-new with RETRY_POLICY initiator
        assert first_close_event.HasField(
            "workflow_execution_continued_as_new_event_attributes"
        ), "Expected first run to be continued-as-new for retry"
        can_attrs = (
            first_close_event.workflow_execution_continued_as_new_event_attributes
        )
        assert (
            can_attrs.initiator == workflow_pb2.CONTINUE_AS_NEW_INITIATOR_RETRY_POLICY
        ), f"Expected RETRY_POLICY initiator, got {can_attrs.initiator}"

        # Walk to the second run and confirm it ends Failed (no more retries)
        second_run_id = can_attrs.new_execution_run_id
        second_run_execution = WorkflowExecution(
            workflow_id=execution.workflow_id,
            run_id=second_run_id,
        )
        second_close = await _wait_for_close(helper, second_run_execution)
        second_close_event = second_close.history.events[-1]
        assert second_close_event.HasField(
            "workflow_execution_failed_event_attributes"
        ), "Expected second run to fail (no more retries)"


async def test_workflow_no_retry_when_policy_unset(helper: CadenceHelper):
    """Without a retry_policy the workflow fails after a single run."""
    async with helper.worker(wf_retry_registry) as worker:
        execution = await worker.client.start_workflow(
            "AlwaysFailsWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        close = await _wait_for_close(helper, execution)
        close_event = close.history.events[-1]

        assert close_event.HasField("workflow_execution_failed_event_attributes"), (
            "Expected single-run failure without retry_policy"
        )
        # No ContinuedAsNew event in history means the server never scheduled a retry
        async with helper.client() as client:
            full: GetWorkflowExecutionHistoryResponse = (
                await client.workflow_stub.GetWorkflowExecutionHistory(
                    GetWorkflowExecutionHistoryRequest(
                        domain=DOMAIN_NAME,
                        workflow_execution=execution,
                        skip_archival=True,
                    )
                )
            )
        continued_events = [
            e
            for e in full.history.events
            if e.HasField("workflow_execution_continued_as_new_event_attributes")
        ]
        assert not continued_events, (
            "No continued-as-new event expected without retry_policy"
        )


async def test_workflow_non_retryable_error_skips_retries(helper: CadenceHelper):
    """A workflow error whose class name is in non_retryable_error_reasons is not retried."""
    async with helper.worker(wf_retry_registry) as worker:
        execution = await worker.client.start_workflow(
            "NonRetryableWorkflowErrorWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
            retry_policy={
                "initial_interval": timedelta(seconds=1),
                "backoff_coefficient": 1.0,
                "maximum_attempts": 5,
                "non_retryable_error_reasons": ["NonRetryableWorkflowError"],
            },
        )

        close = await _wait_for_close(helper, execution)
        close_event = close.history.events[-1]

        assert close_event.HasField("workflow_execution_failed_event_attributes"), (
            "Expected failure on first attempt"
        )

        # Verify the failure reason matches the exception class name
        failure_reason = (
            close_event.workflow_execution_failed_event_attributes.failure.reason
        )
        assert failure_reason == "NonRetryableWorkflowError", (
            f"Expected reason 'NonRetryableWorkflowError', got '{failure_reason}'"
        )

        # Confirm no retry was triggered
        async with helper.client() as client:
            full: GetWorkflowExecutionHistoryResponse = (
                await client.workflow_stub.GetWorkflowExecutionHistory(
                    GetWorkflowExecutionHistoryRequest(
                        domain=DOMAIN_NAME,
                        workflow_execution=execution,
                        skip_archival=True,
                    )
                )
            )
        continued_events = [
            e
            for e in full.history.events
            if e.HasField("workflow_execution_continued_as_new_event_attributes")
        ]
        assert not continued_events, "Non-retryable error must not trigger a retry"
