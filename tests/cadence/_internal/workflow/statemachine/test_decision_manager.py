import asyncio
from asyncio import CancelledError

import pytest

from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence.api.v1 import history, decision
from cadence.api.v1.common_pb2 import Payload


async def test_activity_dispatch():
    decisions = DecisionManager(asyncio.get_event_loop())

    activity_result = decisions.schedule_activity(
        decision.ScheduleActivityTaskDecisionAttributes()
    )
    decisions.handle_history_event(activity_scheduled(1, "0"))
    decisions.handle_history_event(activity_started(2, 1))
    decisions.handle_history_event(activity_completed(3, 1, Payload(data=b"completed")))

    assert activity_result.done() is True
    assert activity_result.result() == Payload(data=b"completed")


async def test_simple_cancellation():
    decisions = DecisionManager(asyncio.get_event_loop())

    activity_result = decisions.schedule_activity(
        decision.ScheduleActivityTaskDecisionAttributes()
    )
    activity_result.cancel()

    assert activity_result.done() is True
    assert activity_result.cancelled() is True


async def test_cancellation_not_immediate():
    decisions = DecisionManager(asyncio.get_event_loop())

    activity_result = decisions.schedule_activity(
        decision.ScheduleActivityTaskDecisionAttributes()
    )
    decisions.handle_history_event(activity_scheduled(1, "0"))
    activity_result.cancel()

    assert activity_result.done() is False
    assert activity_result.cancelled() is False


async def test_cancellation_completed():
    decisions = DecisionManager(asyncio.get_event_loop())

    activity_result = decisions.schedule_activity(
        decision.ScheduleActivityTaskDecisionAttributes()
    )
    decisions.handle_history_event(activity_scheduled(1, "0"))
    activity_result.cancel()
    decisions.handle_history_event(
        history.HistoryEvent(
            event_id=2,
            activity_task_cancel_requested_event_attributes=history.ActivityTaskCancelRequestedEventAttributes(
                activity_id="0"
            ),
        )
    )
    decisions.handle_history_event(
        history.HistoryEvent(
            event_id=3,
            activity_task_canceled_event_attributes=history.ActivityTaskCanceledEventAttributes(
                scheduled_event_id=1, details=Payload(data=b"oh no")
            ),
        )
    )

    assert activity_result.done() is True
    assert activity_result.cancelled() is True
    with pytest.raises(CancelledError, match="oh no"):
        activity_result.result()


async def test_collect_decisions():
    decisions = DecisionManager(asyncio.get_event_loop())

    activity1 = decisions.schedule_activity(
        decision.ScheduleActivityTaskDecisionAttributes()
    )
    activity2 = decisions.schedule_activity(
        decision.ScheduleActivityTaskDecisionAttributes()
    )

    # Order matters
    assert decisions.collect_pending_decisions() == [
        decision.Decision(
            schedule_activity_task_decision_attributes=decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0"
            )
        ),
        decision.Decision(
            schedule_activity_task_decision_attributes=decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="1"
            )
        ),
    ]
    assert activity1.done() is False
    assert activity2.done() is False


async def test_collect_decisions_ignore_empty():
    decisions = DecisionManager(asyncio.get_event_loop())

    _ = decisions.schedule_activity(decision.ScheduleActivityTaskDecisionAttributes())
    decisions.handle_history_event(activity_scheduled(1, "0"))

    assert decisions.collect_pending_decisions() == []


async def test_collection_decisions_reordering():
    # Decisions should be emitted in the order that they happened within the workflow
    decisions = DecisionManager(asyncio.get_event_loop())

    activity1 = decisions.schedule_activity(
        decision.ScheduleActivityTaskDecisionAttributes()
    )
    activity2 = decisions.schedule_activity(
        decision.ScheduleActivityTaskDecisionAttributes()
    )

    assert decisions.collect_pending_decisions() == [
        decision.Decision(
            schedule_activity_task_decision_attributes=decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0"
            )
        ),
        decision.Decision(
            schedule_activity_task_decision_attributes=decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="1"
            )
        ),
    ]

    decisions.handle_history_event(activity_scheduled(1, "0"))
    decisions.handle_history_event(activity_scheduled(2, "1"))
    # cancel them in reverse order
    activity2.cancel()
    activity1.cancel()

    # Order matters
    assert decisions.collect_pending_decisions() == [
        decision.Decision(
            request_cancel_activity_task_decision_attributes=decision.RequestCancelActivityTaskDecisionAttributes(
                activity_id="1"
            )
        ),
        decision.Decision(
            request_cancel_activity_task_decision_attributes=decision.RequestCancelActivityTaskDecisionAttributes(
                activity_id="0"
            )
        ),
    ]
    assert activity1.done() is False
    assert activity2.done() is False


def activity_scheduled(event_id: int, activity_id: str) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
            activity_id=activity_id
        ),
    )


def activity_started(event_id: int, scheduled_id: int) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        activity_task_started_event_attributes=history.ActivityTaskStartedEventAttributes(
            scheduled_event_id=scheduled_id
        ),
    )


def activity_completed(
    event_id: int, scheduled_id: int, result: Payload
) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        activity_task_completed_event_attributes=history.ActivityTaskCompletedEventAttributes(
            scheduled_event_id=scheduled_id, result=result
        ),
    )
