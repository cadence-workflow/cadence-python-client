from asyncio import CancelledError

import pytest

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
from cadence.api.v1.common_pb2 import Payload, Failure
from cadence.api.v1.decision_pb2 import RequestCancelActivityTaskDecisionAttributes
from cadence.error import ActivityFailure

### These tests have to be async because they rely on the presence of an eventloop


async def test_activity_state_machine_initiated():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed)

    assert completed.done() is False
    assert m.get_decision() == decision.Decision(
        schedule_activity_task_decision_attributes=attrs
    )


async def test_activity_state_machine_cancelled_before_initiated():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()

    m = ActivityStateMachine(attrs, completed)
    res = m.request_cancel()

    assert res is True
    assert completed.done() is True
    assert completed.cancelled() is True
    assert m.get_decision() == record_immediate_cancel(attrs)


async def test_activity_state_machine_cancelled_after_initiated():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed)

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
    m = ActivityStateMachine(attrs, completed)

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.handle_started(history.ActivityTaskStartedEventAttributes())
    m.handle_completed(
        history.ActivityTaskCompletedEventAttributes(result=Payload(data=b"result"))
    )

    assert completed.done() is True
    assert m.get_decision() is None
    assert completed.result() == Payload(data=b"result")


async def test_activity_state_machine_timeout():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed)

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    heartbeat_details = Payload(data=b'{"progress": 42}')
    m.handle_timeout(
        history.ActivityTaskTimedOutEventAttributes(
            timeout_type=4,  # TIMEOUT_TYPE_HEARTBEAT
            details=heartbeat_details,
            last_failure=Failure(
                reason="RuntimeError",
                details=b"Traceback (most recent call last):\nRuntimeError: boom",
            ),
        )
    )

    assert completed.done() is True
    assert m.get_decision() is None
    with pytest.raises(ActivityFailure, match="TIMEOUT_TYPE_HEARTBEAT") as exc_info:
        completed.result()
    assert exc_info.value.failure_details == (
        "Traceback (most recent call last):\nRuntimeError: boom"
    )
    assert exc_info.value.heartbeat_details == heartbeat_details
    assert exc_info.value.heartbeat_details.data == b'{"progress": 42}'


async def test_activity_state_machine_failed():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed)

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
    with pytest.raises(
        ActivityFailure, match="RuntimeError.*error message"
    ) as exc_info:
        completed.result()
    assert exc_info.value.failure_details == (
        "Traceback (most recent call last):\nRuntimeError: error message"
    )


async def test_activity_state_machine_cancel_confirmed():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed)

    m.handle_scheduled(history.ActivityTaskScheduledEventAttributes(activity_id="a"))
    m.request_cancel()
    m.handle_cancel_requested(history.ActivityTaskCancelRequestedEventAttributes())

    assert m.get_decision() is None
    assert completed.done() is False
    assert m.get_decision() is None


async def test_activity_state_machine_complete_after_cancel():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="a")
    completed = DecisionFuture[Payload]()
    m = ActivityStateMachine(attrs, completed)

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
    m = ActivityStateMachine(attrs, completed)

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
    m = ActivityStateMachine(attrs, completed)

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
    m = ActivityStateMachine(attrs, completed)

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
