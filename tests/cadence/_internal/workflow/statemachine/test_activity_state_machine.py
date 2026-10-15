from asyncio import CancelledError
from datetime import timedelta

import pytest
from google.protobuf.duration_pb2 import Duration

from cadence._internal.workflow.statemachine.activity_state_machine import (
    ActivityStateMachine,
)
from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionFuture,
)
from cadence._internal.workflow.statemachine.nondeterminism import (
    record_immediate_cancel,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import (
    FAILURE_CATEGORY_POLL,
    ActivityType,
    Failure,
    FailureOptions,
    Payload,
)
from cadence.api.v1.decision_pb2 import RequestCancelActivityTaskDecisionAttributes
from cadence.api.v1.workflow_pb2 import TimeoutType
from cadence.data_converter import DefaultDataConverter
from cadence.error import (
    ActivityError,
    ApplicationError,
    CadenceTimeoutError,
    FailureCategory,
)
from cadence.error import TimeoutType as CadenceTimeoutType

### These tests have to be async because they rely on the presence of an eventloop


async def test_activity_state_machine_initiated():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    assert completed.done() is False
    assert m.get_decision() == decision.Decision(
        schedule_activity_task_decision_attributes=attrs
    )


async def test_activity_state_machine_cancelled_before_initiated():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()

    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())
    res = m.request_cancel()

    assert res is True
    assert completed.done() is True
    assert completed.cancelled() is True
    assert m.get_decision() == record_immediate_cancel(attrs)


async def test_activity_state_machine_cancelled_after_initiated():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    res = m.request_cancel()

    assert res is True
    assert completed.done() is False
    assert m.get_decision() == decision.Decision(
        request_cancel_activity_task_decision_attributes=RequestCancelActivityTaskDecisionAttributes(
            activity_id="a"
        )
    )


async def test_activity_state_machine_completed():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.handle_started(history.ActivityTaskStartedEventAttributes())
    m.handle_completed(
        history.ActivityTaskCompletedEventAttributes(result=Payload(data=b"result"))
    )

    assert completed.done() is True
    assert m.get_decision() is None
    assert completed.result() == Payload(data=b"result")


async def test_activity_state_machine_timeout():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(
        activity_id="a", activity_type=ActivityType(name="my_activity")
    )
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.handle_timeout(
        history.ActivityTaskTimedOutEventAttributes(
            timeout_type=TimeoutType.TIMEOUT_TYPE_HEARTBEAT,
            details=Payload(data=b'{"progress": 42}'),
            last_failure=Failure(
                reason="RuntimeError",
                details=b"Traceback (most recent call last):\nRuntimeError: boom",
            ),
        )
    )

    assert completed.done() is True
    assert m.get_decision() is None
    with pytest.raises(ActivityError, match="HEARTBEAT") as exc_info:
        completed.result()
    error = exc_info.value
    assert error.activity_id == "a"
    assert error.activity_type == "my_activity"
    timeout = error.cause
    assert isinstance(timeout, CadenceTimeoutError)
    assert timeout.timeout_type is CadenceTimeoutType.HEARTBEAT
    assert timeout.has_details()
    assert timeout.details(dict) == [{"progress": 42}]


async def test_activity_state_machine_timeout_without_details():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(
        activity_id="a", activity_type=ActivityType(name="my_activity")
    )
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.handle_timeout(
        history.ActivityTaskTimedOutEventAttributes(
            timeout_type=TimeoutType.TIMEOUT_TYPE_START_TO_CLOSE,
        )
    )

    with pytest.raises(ActivityError) as exc_info:
        completed.result()
    timeout = exc_info.value.cause
    assert isinstance(timeout, CadenceTimeoutError)
    assert timeout.timeout_type is CadenceTimeoutType.START_TO_CLOSE
    assert not timeout.has_details()
    assert timeout.details(dict) == []


async def test_activity_state_machine_failed():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.handle_started(history.ActivityTaskStartedEventAttributes())
    m.handle_failed(
        history.ActivityTaskFailedEventAttributes(
            failure=Failure(
                reason="RuntimeError",
                details=b"Traceback (most recent call last):\nRuntimeError: error message",
            )
        )
    )

    assert completed.done() is True
    assert m.get_decision() is None
    with pytest.raises(ActivityError, match="RuntimeError.*error message") as exc_info:
        completed.result()
    cause = exc_info.value.cause
    assert isinstance(cause, ApplicationError)
    assert cause.reason == "RuntimeError"


async def test_activity_state_machine_failed_with_application_error():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.handle_failed(
        history.ActivityTaskFailedEventAttributes(
            failure=Failure(
                reason="not-ready",
                details=b'{"retry_in": 5} "later"',
                options=FailureOptions(
                    failure_category=FAILURE_CATEGORY_POLL,
                    next_retry_interval=Duration(seconds=5),
                ),
            )
        )
    )

    with pytest.raises(ActivityError) as exc_info:
        completed.result()
    cause = exc_info.value.cause
    assert isinstance(cause, ApplicationError)
    assert cause.reason == "not-ready"
    assert cause.details(dict, str) == [{"retry_in": 5}, "later"]
    assert cause.failure_category is FailureCategory.POLL
    assert cause.next_retry_delay == timedelta(seconds=5)


async def test_activity_state_machine_cancel_confirmed():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.request_cancel()
    m.handle_cancel_requested(history.ActivityTaskCancelRequestedEventAttributes())

    assert m.get_decision() is None
    assert completed.done() is False
    assert m.get_decision() is None


async def test_activity_state_machine_complete_after_cancel():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.request_cancel()
    m.handle_cancel_requested(history.ActivityTaskCancelRequestedEventAttributes())
    m.handle_completed(
        history.ActivityTaskCompletedEventAttributes(result=Payload(data=b"result"))
    )

    assert m.get_decision() is None
    assert completed.done() is True
    assert completed.result() == Payload(data=b"result")


async def test_activity_state_machine_cancel_accepted():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.request_cancel()
    m.handle_cancel_requested(history.ActivityTaskCancelRequestedEventAttributes())
    m.handle_canceled(
        history.ActivityTaskCanceledEventAttributes(
            details=Payload(data="error message".encode())
        )
    )

    assert m.get_decision() is None
    assert completed.done() is True
    assert completed.cancelled() is True
    with pytest.raises(CancelledError, match="error message"):
        completed.result()


async def test_activity_state_machine_cancel_failed():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.request_cancel()
    m.handle_cancel_requested(history.ActivityTaskCancelRequestedEventAttributes())
    m.handle_cancel_failed(history.RequestCancelActivityTaskFailedEventAttributes())

    assert m.get_decision() is None
    assert completed.done() is False
    assert completed.cancelled() is False


async def test_activity_state_machine_completed_after_cancel_failed():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed, DefaultDataConverter())

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.request_cancel()
    m.handle_cancel_requested(history.ActivityTaskCancelRequestedEventAttributes())
    m.handle_cancel_failed(history.RequestCancelActivityTaskFailedEventAttributes())
    m.handle_completed(
        history.ActivityTaskCompletedEventAttributes(result=Payload(data=b"result"))
    )

    assert m.get_decision() is None
    assert completed.result() == Payload(data=b"result")
    assert completed.done() is True
    assert completed.cancelled() is False
