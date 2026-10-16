from datetime import timedelta

from cadence import Registry, activity, workflow
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.history_pb2 import EventFilterType, HistoryEvent
from cadence.api.v1.service_workflow_pb2 import GetWorkflowExecutionHistoryRequest
from cadence.client import Client
from cadence.workflow import RetryPolicy
from cadence.error import (
    ActivityError,
    ApplicationError,
    ChildWorkflowError,
    FailureCategory,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()

NO_RETRY: RetryPolicy = {
    "maximum_attempts": 1,
    "initial_interval": timedelta(seconds=1),
    "backoff_coefficient": 1.0,
}


@registry.activity()
async def application_failure(code: int) -> None:
    raise ApplicationError(
        "lookup-failed",
        {"code": code},
        "not found",
        failure_category=FailureCategory.FATAL,
    )


@registry.activity()
async def retry_with_delay() -> int:
    attempt = activity.info().attempt
    if attempt == 0:
        raise ApplicationError("try-again", next_retry_delay=timedelta(seconds=1))
    return attempt


@registry.workflow()
class CatchActivityApplicationErrorWorkflow:
    @workflow.run
    async def run(self, code: int) -> list:
        try:
            await application_failure.with_options(
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=NO_RETRY,
            ).execute(code)
        except ActivityError as e:
            assert isinstance(e.cause, ApplicationError)
            return [e.cause.reason, *e.cause.details(dict, str)]
        raise RuntimeError("expected activity to fail")


@registry.workflow()
class ReraiseActivityApplicationErrorWorkflow:
    @workflow.run
    async def run(self, code: int) -> None:
        try:
            await application_failure.with_options(
                schedule_to_close_timeout=timedelta(seconds=10),
                retry_policy=NO_RETRY,
            ).execute(code)
        except ActivityError as e:
            assert e.cause is not None
            raise e.cause


@registry.workflow()
class ApplicationErrorWorkflow:
    @workflow.run
    async def run(self, code: int) -> None:
        raise ApplicationError("workflow-failed", {"code": code})


@registry.workflow()
class CatchChildApplicationErrorWorkflow:
    @workflow.run
    async def run(self, code: int) -> list:
        try:
            await workflow.execute_child_workflow(
                "ApplicationErrorWorkflow",
                type(None),
                code,
                execution_start_to_close_timeout=timedelta(seconds=10),
            )
        except ChildWorkflowError as e:
            assert isinstance(e.cause, ApplicationError)
            return [e.cause.reason, *e.cause.details(dict)]
        raise RuntimeError("expected child workflow to fail")


@registry.workflow()
class NextRetryDelayWorkflow:
    @workflow.run
    async def run(self) -> int:
        return await retry_with_delay.with_options(
            schedule_to_close_timeout=timedelta(seconds=60),
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy={
                "initial_interval": timedelta(seconds=30),
                "backoff_coefficient": 1.0,
                "maximum_attempts": 3,
            },
        ).execute()


async def test_activity_application_error_details_round_trip(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "CatchActivityApplicationErrorWorkflow",
            7,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        close_event = await _close_event(worker.client, execution)
        result = close_event.workflow_execution_completed_event_attributes.result
        assert result.data == b'["lookup-failed",{"code":7},"not found"]'

        failed = [
            e.activity_task_failed_event_attributes
            for e in await _history(worker.client, execution)
            if e.HasField("activity_task_failed_event_attributes")
        ]
        assert len(failed) == 1
        assert failed[0].failure.reason == "lookup-failed"
        assert failed[0].failure.details == b'{"code":7} "not found"'


async def test_reraised_activity_application_error_fails_workflow(
    helper: CadenceHelper,
):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "ReraiseActivityApplicationErrorWorkflow",
            7,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        close_event = await _close_event(worker.client, execution)
        failure = close_event.workflow_execution_failed_event_attributes.failure
        assert failure.reason == "lookup-failed"
        assert failure.details == b'{"code":7} "not found"'


async def test_workflow_application_error_reason_and_details(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "ApplicationErrorWorkflow",
            3,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        close_event = await _close_event(worker.client, execution)
        failure = close_event.workflow_execution_failed_event_attributes.failure
        assert failure.reason == "workflow-failed"
        assert failure.details == b'{"code":3}'


async def test_child_workflow_application_error(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "CatchChildApplicationErrorWorkflow",
            5,
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        close_event = await _close_event(worker.client, execution)
        result = close_event.workflow_execution_completed_event_attributes.result
        assert result.data == b'["workflow-failed",{"code":5}]'


async def test_next_retry_delay_overrides_retry_policy_interval(
    helper: CadenceHelper,
):
    """The retry policy waits 30s between attempts, but the activity asks for 1s."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "NextRetryDelayWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=60),
        )

        close_event = await _close_event(worker.client, execution)
        result = close_event.workflow_execution_completed_event_attributes.result
        assert result.data == b"1"

        events = await _history(worker.client, execution)
        elapsed = events[-1].event_time.ToDatetime() - events[0].event_time.ToDatetime()
        assert elapsed < timedelta(seconds=20)


async def _close_event(client: Client, execution: WorkflowExecution) -> HistoryEvent:
    response = await client.workflow_stub.GetWorkflowExecutionHistory(
        GetWorkflowExecutionHistoryRequest(
            domain=DOMAIN_NAME,
            workflow_execution=execution,
            wait_for_new_event=True,
            history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
            skip_archival=True,
        )
    )
    event: HistoryEvent = response.history.events[-1]
    return event


async def _history(client: Client, execution: WorkflowExecution) -> list[HistoryEvent]:
    response = await client.workflow_stub.GetWorkflowExecutionHistory(
        GetWorkflowExecutionHistoryRequest(
            domain=DOMAIN_NAME,
            workflow_execution=execution,
            skip_archival=True,
        )
    )
    return list(response.history.events)
