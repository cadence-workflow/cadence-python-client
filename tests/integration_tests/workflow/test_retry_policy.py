from datetime import timedelta

from cadence import workflow, Registry, activity
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
