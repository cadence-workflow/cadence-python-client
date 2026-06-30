import asyncio

from cadence._internal.workflow.decision_events_iterator import DecisionEventsIterator
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence._internal.workflow.statemachine.marker_state_machine import (
    MARKER_ID_HEADER_KEY,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload


async def test_replay_marker_event_is_preloaded_before_marker_decision_exists():
    decisions = DecisionManager(asyncio.get_event_loop())
    marker_attrs = decision.RecordMarkerDecisionAttributes(
        marker_name="SideEffect",
        details=Payload(data=b"recorded-value"),
    )
    decision_events = next(iter(DecisionEventsIterator(_history_with_marker_output())))

    assert decision_events.replay is True
    assert len(decision_events.markers) == 1

    for marker_event in decision_events.markers:
        decisions.handle_history_event(marker_event)

    decisions.record_marker(marker_attrs)
    assert decisions.collect_pending_decisions() == [
        decision.Decision(record_marker_decision_attributes=marker_attrs)
    ]

    for event in decision_events.output:
        decisions.handle_history_event(event)

    assert decisions.collect_pending_decisions() == []


async def test_current_decision_task_emits_record_marker_decision():
    decisions = DecisionManager(asyncio.get_event_loop())
    decision_events = next(iter(DecisionEventsIterator(_current_decision_history())))
    marker_attrs = decision.RecordMarkerDecisionAttributes(
        marker_name="MutableSideEffect",
        details=Payload(data=b"new-value"),
    )

    assert decision_events.replay is False
    assert decision_events.output == []
    assert decision_events.markers == []

    decisions.record_marker(marker_attrs)

    assert decisions.collect_pending_decisions() == [
        decision.Decision(record_marker_decision_attributes=marker_attrs)
    ]


async def test_multiple_replayed_marker_outputs_complete_in_decision_order():
    decisions = DecisionManager(asyncio.get_event_loop())
    first_attrs = decision.RecordMarkerDecisionAttributes(
        marker_name="SideEffect",
        details=Payload(data=b"first"),
    )
    second_attrs = decision.RecordMarkerDecisionAttributes(
        marker_name="LocalActivity",
        details=Payload(data=b"second"),
    )
    decision_events = next(
        iter(DecisionEventsIterator(_history_with_multiple_marker_outputs()))
    )

    assert decision_events.replay is True
    assert len(decision_events.markers) == 2

    for marker_event in decision_events.markers:
        decisions.handle_history_event(marker_event)

    decisions.record_marker(first_attrs)
    decisions.record_marker(second_attrs)
    assert decisions.collect_pending_decisions() == [
        decision.Decision(record_marker_decision_attributes=first_attrs),
        decision.Decision(record_marker_decision_attributes=second_attrs),
    ]

    for event in decision_events.output:
        decisions.handle_history_event(event)

    assert decisions.collect_pending_decisions() == []


def _current_decision_history() -> list[history.HistoryEvent]:
    return [
        _workflow_started(1),
        _decision_task_scheduled(2),
        _decision_task_started(3, scheduled_event_id=2),
    ]


def _history_with_marker_output() -> list[history.HistoryEvent]:
    return [
        _workflow_started(1),
        _decision_task_scheduled(2),
        _decision_task_started(3, scheduled_event_id=2),
        _decision_task_completed(4, scheduled_event_id=2, started_event_id=3),
        _marker_recorded(5, "SideEffect", Payload(data=b"recorded-value"), "0"),
        _decision_task_scheduled(6),
        _decision_task_started(7, scheduled_event_id=6),
    ]


def _history_with_multiple_marker_outputs() -> list[history.HistoryEvent]:
    return [
        _workflow_started(1),
        _decision_task_scheduled(2),
        _decision_task_started(3, scheduled_event_id=2),
        _decision_task_completed(4, scheduled_event_id=2, started_event_id=3),
        _marker_recorded(5, "SideEffect", Payload(data=b"first"), "0"),
        _marker_recorded(6, "LocalActivity", Payload(data=b"second"), "1"),
        _decision_task_scheduled(7),
        _decision_task_started(8, scheduled_event_id=7),
    ]


def _workflow_started(event_id: int) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        workflow_execution_started_event_attributes=history.WorkflowExecutionStartedEventAttributes(),
    )


def _decision_task_scheduled(event_id: int) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        decision_task_scheduled_event_attributes=history.DecisionTaskScheduledEventAttributes(),
    )


def _decision_task_started(
    event_id: int,
    *,
    scheduled_event_id: int,
) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        decision_task_started_event_attributes=history.DecisionTaskStartedEventAttributes(
            scheduled_event_id=scheduled_event_id,
        ),
    )


def _decision_task_completed(
    event_id: int,
    *,
    scheduled_event_id: int,
    started_event_id: int,
) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        decision_task_completed_event_attributes=history.DecisionTaskCompletedEventAttributes(
            scheduled_event_id=scheduled_event_id,
            started_event_id=started_event_id,
        ),
    )


def _marker_recorded(
    event_id: int,
    marker_name: str,
    details: Payload,
    marker_id: str,
) -> history.HistoryEvent:
    attrs = history.MarkerRecordedEventAttributes(
        marker_name=marker_name,
        details=details,
    )
    attrs.header.fields[MARKER_ID_HEADER_KEY].CopyFrom(
        Payload(data=marker_id.encode("utf-8"))
    )
    return history.HistoryEvent(
        event_id=event_id,
        marker_recorded_event_attributes=attrs,
    )
