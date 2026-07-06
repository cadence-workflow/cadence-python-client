import asyncio
from asyncio import CancelledError

import pytest

from cadence.error import ChildWorkflowError, StartChildWorkflowExecutionFailed
from cadence._internal.workflow.statemachine.cancellation import MARKER_PREFIX
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence._internal.workflow.statemachine.event_dispatcher import (
    EventDispatcher,
    resolve_id_attr,
)
from cadence._internal.workflow.statemachine.marker_state_machine import (
    encode_marker_details,
)
from cadence._internal.workflow.statemachine.nondeterminism import NonDeterminismError
from cadence._internal.workflow.statemachine.signal_external_workflow_state_machine import (
    SignalExternalWorkflowFailed,
)
from cadence.api.v1 import history, decision
from cadence.api.v1.common_pb2 import Payload, WorkflowExecution, WorkflowType


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


async def test_record_marker_collects_in_workflow_order():
    decisions = DecisionManager(asyncio.get_event_loop())
    marker_attrs = decision.RecordMarkerDecisionAttributes(
        marker_name="SideEffect", details=Payload(data=b"marker")
    )

    decisions.start_timer(decision.StartTimerDecisionAttributes())
    recorded = decisions.record_marker(marker_attrs)
    decisions.schedule_activity(decision.ScheduleActivityTaskDecisionAttributes())

    assert recorded == Payload(data=b"marker")
    assert decisions.collect_pending_decisions() == [
        decision.Decision(
            start_timer_decision_attributes=decision.StartTimerDecisionAttributes(
                timer_id="0"
            )
        ),
        decision.Decision(record_marker_decision_attributes=marker_attrs),
        decision.Decision(
            schedule_activity_task_decision_attributes=decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="2"
            )
        ),
    ]


async def test_record_marker_history_clears_pending_decision():
    decisions = DecisionManager(asyncio.get_event_loop())
    marker_attrs = decision.RecordMarkerDecisionAttributes(
        marker_name="SideEffect", details=Payload(data=b"marker")
    )

    decisions.record_marker(marker_attrs)

    decisions.handle_history_event(
        marker_recorded(1, "SideEffect", Payload(data=b"marker"), context_id="0")
    )

    assert decisions.collect_pending_decisions() == []


async def test_replayed_marker_returns_recorded_details():
    decisions = DecisionManager(asyncio.get_event_loop())
    recorded = marker_recorded(
        1, "SideEffect", Payload(data=b"history-value"), context_id="0"
    )

    with decisions.track_nondeterminism(True, [recorded]):
        result = decisions.record_marker(
            decision.RecordMarkerDecisionAttributes(
                marker_name="SideEffect", details=Payload(data=b"current-value")
            )
        )

    assert result == Payload(data=b"history-value")


async def test_replayed_marker_name_mismatch_is_nondeterministic():
    decisions = DecisionManager(asyncio.get_event_loop())
    recorded = marker_recorded(
        1, "SideEffect", Payload(data=b"history-value"), context_id="0"
    )

    with pytest.raises(NonDeterminismError):
        with decisions.track_nondeterminism(True, [recorded]):
            decisions.record_marker(
                decision.RecordMarkerDecisionAttributes(marker_name="LocalActivity")
            )


async def test_replayed_marker_order_mismatch_is_nondeterministic():
    decisions = DecisionManager(asyncio.get_event_loop())
    first = marker_recorded(1, "SideEffect", Payload(data=b"first"), context_id="0")
    second = marker_recorded(
        2, "LocalActivity", Payload(data=b"second"), context_id="1"
    )

    with pytest.raises(NonDeterminismError):
        with decisions.track_nondeterminism(True, [first, second]):
            # Auto-assigned ID is "0"; history expects "SideEffect" at that slot,
            # so recording "LocalActivity" first is a non-determinism violation.
            decisions.record_marker(
                decision.RecordMarkerDecisionAttributes(marker_name="LocalActivity")
            )


async def test_replayed_marker_missing_from_workflow_is_nondeterministic():
    decisions = DecisionManager(asyncio.get_event_loop())
    recorded = marker_recorded(
        1, "SideEffect", Payload(data=b"history-value"), context_id="0"
    )

    with pytest.raises(NonDeterminismError):
        with decisions.track_nondeterminism(True, [recorded]):
            pass


async def test_replayed_marker_without_context_id_is_nondeterministic():
    decisions = DecisionManager(asyncio.get_event_loop())
    # Raw details with no length-prefix encoding — treated as produced by another SDK.
    recorded = marker_recorded(1, "SideEffect", Payload(data=b"history-value"))

    with pytest.raises(NonDeterminismError):
        with decisions.track_nondeterminism(True, [recorded]):
            decisions.record_marker(
                decision.RecordMarkerDecisionAttributes(marker_name="SideEffect")
            )


async def test_record_marker_ids_are_sequential():
    decisions = DecisionManager(asyncio.get_event_loop())

    decisions.record_marker(
        decision.RecordMarkerDecisionAttributes(marker_name="SideEffect")
    )
    decisions.record_marker(
        decision.RecordMarkerDecisionAttributes(marker_name="LocalActivity")
    )

    keys = list(decisions.state_machines.keys())
    assert keys[0].id == "SideEffect_0"
    assert keys[1].id == "LocalActivity_1"


async def test_record_marker_requires_marker_name():
    decisions = DecisionManager(asyncio.get_event_loop())

    with pytest.raises(ValueError, match="marker_name is required"):
        decisions.record_marker(decision.RecordMarkerDecisionAttributes())

    assert decisions.collect_pending_decisions() == []


async def test_cancel_marker_is_not_logged_as_unknown_marker_name(caplog):
    # The Cancel_ immediate-cancellation marker (cancellation.py) is Python-specific
    # and encodes a JSON object in Details, not a [context_id, user_data] pair. It
    # must not be mistaken for an unrecognized marker_name and warned about.
    decisions = DecisionManager(asyncio.get_event_loop())
    cancel_marker = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=f"{MARKER_PREFIX}0",
            details=Payload(data=b'{"canceled": true, "type": "ACTIVITY"}'),
        ),
    )

    with caplog.at_level("WARNING"):
        decisions.handle_history_event(cancel_marker)

    assert "unknown marker_name" not in caplog.text


async def test_version_marker_is_not_flagged_as_nondeterministic():
    # Version markers are exempt from non-determinism tracking.
    # History that includes a Version marker must replay without error, and the
    # Version expectation is never added so complete_replay doesn't fail either.
    decisions = DecisionManager(asyncio.get_event_loop())
    # History: Version_0 (exempt) then SideEffect_1 (tracked).
    version_recorded = marker_recorded(
        1, "Version", Payload(data=b"v1"), context_id="0"
    )
    side_effect_recorded = marker_recorded(
        2, "SideEffect", Payload(data=b"side"), context_id="1"
    )

    with decisions.track_nondeterminism(True, [version_recorded, side_effect_recorded]):
        # counter="0" → key "Version_0"; no expectation created or consumed.
        decisions.record_marker(
            decision.RecordMarkerDecisionAttributes(
                marker_name="Version", details=Payload(data=b"v1")
            )
        )
        # counter="1" → key "SideEffect_1"; expectation from history is consumed.
        decisions.record_marker(
            decision.RecordMarkerDecisionAttributes(
                marker_name="SideEffect", details=Payload(data=b"new")
            )
        )


async def test_replayed_marker_details_come_from_history_not_current_value():
    # Ensure the historical value is returned even when the current call passes different data.
    decisions = DecisionManager(asyncio.get_event_loop())
    recorded = marker_recorded(
        1, "SideEffect", Payload(data=b"history-value"), context_id="0"
    )

    with decisions.track_nondeterminism(True, [recorded]):
        result = decisions.record_marker(
            decision.RecordMarkerDecisionAttributes(
                marker_name="SideEffect", details=Payload(data=b"current-value")
            )
        )

    assert result == Payload(data=b"history-value")


async def test_child_workflow_dispatch():
    decisions = DecisionManager(asyncio.get_event_loop())

    execution, result = decisions.schedule_child_workflow(
        decision.StartChildWorkflowExecutionDecisionAttributes(
            workflow_id="child-wf-1",
            workflow_type=WorkflowType(name="MyWorkflow"),
        ),
        parent_workflow_run_id="parent-run",
    )

    decisions.handle_history_event(child_wf_initiated(1, "child-wf-1"))
    decisions.handle_history_event(
        child_wf_started(2, started_event_id=1, wf_id="child-wf-1", run_id="run-1")
    )
    decisions.handle_history_event(
        child_wf_completed(3, started_event_id=1, result=Payload(data=b"done"))
    )

    assert execution.done() is True
    assert execution.result() == WorkflowExecution(
        workflow_id="child-wf-1", run_id="run-1"
    )
    assert result.done() is True
    assert result.result() == Payload(data=b"done")


async def test_schedule_child_workflow_generates_workflow_id():
    decisions = DecisionManager(asyncio.get_event_loop())

    attrs = decision.StartChildWorkflowExecutionDecisionAttributes(
        workflow_id="",
        workflow_type=WorkflowType(name="MyWorkflow"),
    )
    _execution, result = decisions.schedule_child_workflow(
        attrs, parent_workflow_run_id="parent-run-xyz"
    )

    assert attrs.workflow_id == "parent-run-xyz_0"

    decisions.handle_history_event(child_wf_initiated(1, attrs.workflow_id))
    decisions.handle_history_event(
        child_wf_started(2, started_event_id=1, wf_id=attrs.workflow_id, run_id="run-1")
    )
    decisions.handle_history_event(
        child_wf_completed(3, started_event_id=1, result=Payload(data=b"done"))
    )

    assert result.result() == Payload(data=b"done")


async def test_child_workflow_initiation_failed_dispatch():
    decisions = DecisionManager(asyncio.get_event_loop())

    execution, result = decisions.schedule_child_workflow(
        decision.StartChildWorkflowExecutionDecisionAttributes(
            workflow_id="child-wf-1",
            workflow_type=WorkflowType(name="MyWorkflow"),
        ),
        parent_workflow_run_id="parent-run",
    )

    decisions.handle_history_event(child_wf_initiated(1, "child-wf-1"))
    decisions.handle_history_event(
        history.HistoryEvent(
            event_id=2,
            start_child_workflow_execution_failed_event_attributes=history.StartChildWorkflowExecutionFailedEventAttributes(
                initiated_event_id=1,
                workflow_id="child-wf-1",
                workflow_type=WorkflowType(name="MyWorkflow"),
            ),
        )
    )

    assert execution.done() is True
    assert result.done() is True
    with pytest.raises(StartChildWorkflowExecutionFailed):
        result.result()


async def test_child_workflow_cancel_dispatch():
    decisions = DecisionManager(asyncio.get_event_loop())

    _execution, result = decisions.schedule_child_workflow(
        decision.StartChildWorkflowExecutionDecisionAttributes(
            workflow_id="child-wf-1",
            workflow_type=WorkflowType(name="MyWorkflow"),
        ),
        parent_workflow_run_id="parent-run",
    )

    decisions.handle_history_event(child_wf_initiated(1, "child-wf-1"))
    decisions.handle_history_event(
        child_wf_started(2, started_event_id=1, wf_id="child-wf-1", run_id="run-1")
    )

    # Cancel the child workflow
    result.cancel()

    # cancel_initiated and cancel_failed are dispatched by workflow_execution.workflow_id
    decisions.handle_history_event(
        history.HistoryEvent(
            event_id=3,
            request_cancel_external_workflow_execution_initiated_event_attributes=history.RequestCancelExternalWorkflowExecutionInitiatedEventAttributes(
                workflow_execution=WorkflowExecution(
                    workflow_id="child-wf-1", run_id="run-1"
                ),
            ),
        )
    )
    decisions.handle_history_event(
        history.HistoryEvent(
            event_id=4,
            request_cancel_external_workflow_execution_failed_event_attributes=history.RequestCancelExternalWorkflowExecutionFailedEventAttributes(
                initiated_event_id=3,
            ),
        )
    )

    # Cancel failed — back to STARTED
    assert result.done() is False


async def test_child_workflow_errors_are_child_workflow_error():
    """All child workflow errors share a common base class."""
    decisions = DecisionManager(asyncio.get_event_loop())

    _execution, result = decisions.schedule_child_workflow(
        decision.StartChildWorkflowExecutionDecisionAttributes(
            workflow_id="child-wf-1",
            workflow_type=WorkflowType(name="MyWorkflow"),
        ),
        parent_workflow_run_id="parent-run",
    )

    decisions.handle_history_event(child_wf_initiated(1, "child-wf-1"))
    decisions.handle_history_event(
        history.HistoryEvent(
            event_id=2,
            start_child_workflow_execution_failed_event_attributes=history.StartChildWorkflowExecutionFailedEventAttributes(
                initiated_event_id=1,
                workflow_id="child-wf-1",
                workflow_type=WorkflowType(name="MyWorkflow"),
            ),
        )
    )

    assert result.done() is True
    with pytest.raises(ChildWorkflowError):
        result.result()


def test_resolve_id_attr_empty_path_returns_none():
    attrs = history.TimerStartedEventAttributes(timer_id="timer-1")

    assert resolve_id_attr(attrs, "") is None


def test_event_dispatcher_allows_empty_default_id_attr():
    dispatcher = EventDispatcher()

    class Handler:
        @dispatcher.event()
        def handle(self, _: history.TimerStartedEventAttributes) -> None:
            pass

    _ = Handler  # the decorator's side effect (registering the handler) is what's under test

    action = dispatcher.handlers[history.TimerStartedEventAttributes]
    assert action.id_attr == ""


def child_wf_initiated(event_id: int, workflow_id: str) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        start_child_workflow_execution_initiated_event_attributes=history.StartChildWorkflowExecutionInitiatedEventAttributes(
            workflow_id=workflow_id,
            workflow_type=WorkflowType(name="MyWorkflow"),
        ),
    )


def child_wf_started(
    event_id: int, *, started_event_id: int, wf_id: str, run_id: str
) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        child_workflow_execution_started_event_attributes=history.ChildWorkflowExecutionStartedEventAttributes(
            initiated_event_id=started_event_id,
            workflow_execution=WorkflowExecution(workflow_id=wf_id, run_id=run_id),
        ),
    )


def child_wf_completed(
    event_id: int, *, started_event_id: int, result: Payload
) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        child_workflow_execution_completed_event_attributes=history.ChildWorkflowExecutionCompletedEventAttributes(
            initiated_event_id=started_event_id,
            result=result,
        ),
    )


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


def marker_recorded(
    event_id: int, marker_name: str, details: Payload, context_id: str | None = None
) -> history.HistoryEvent:
    if context_id is not None:
        encoded = encode_marker_details(context_id, details.data)
        attrs = history.MarkerRecordedEventAttributes(
            marker_name=marker_name,
            details=Payload(data=encoded),
        )
    else:
        attrs = history.MarkerRecordedEventAttributes(
            marker_name=marker_name,
            details=details,
        )
    return history.HistoryEvent(
        event_id=event_id,
        marker_recorded_event_attributes=attrs,
    )


async def test_signal_external_workflow_creates_machine():
    decisions = DecisionManager(asyncio.get_event_loop())

    future = decisions.signal_external_workflow(
        decision.SignalExternalWorkflowExecutionDecisionAttributes(
            domain="test-domain",
            workflow_execution=WorkflowExecution(workflow_id="child-wf-1", run_id=""),
            signal_name="my_signal",
            child_workflow_only=True,
        )
    )

    assert future.done() is False
    pending = decisions.collect_pending_decisions()
    assert len(pending) == 1
    assert (
        pending[0].signal_external_workflow_execution_decision_attributes.signal_name
        == "my_signal"
    )


async def test_signal_external_workflow_sets_control():
    decisions = DecisionManager(asyncio.get_event_loop())

    attrs = decision.SignalExternalWorkflowExecutionDecisionAttributes(
        domain="test-domain",
        workflow_execution=WorkflowExecution(workflow_id="child-wf-1", run_id=""),
        signal_name="my_signal",
        child_workflow_only=True,
    )
    decisions.signal_external_workflow(attrs)

    assert attrs.control == b"0"


async def test_signal_external_workflow_multiple_signals():
    decisions = DecisionManager(asyncio.get_event_loop())

    future1 = decisions.signal_external_workflow(
        decision.SignalExternalWorkflowExecutionDecisionAttributes(
            domain="test-domain",
            workflow_execution=WorkflowExecution(workflow_id="child-wf-1", run_id=""),
            signal_name="signal_a",
            child_workflow_only=True,
        )
    )
    future2 = decisions.signal_external_workflow(
        decision.SignalExternalWorkflowExecutionDecisionAttributes(
            domain="test-domain",
            workflow_execution=WorkflowExecution(workflow_id="child-wf-1", run_id=""),
            signal_name="signal_b",
            child_workflow_only=True,
        )
    )

    assert len(decisions.collect_pending_decisions()) == 2

    decisions.handle_history_event(signal_initiated(1, signal_id="0"))
    decisions.handle_history_event(signal_initiated(2, signal_id="1"))
    decisions.handle_history_event(signal_completed(3, initiated_event_id=1))
    decisions.handle_history_event(signal_completed(4, initiated_event_id=2))

    assert future1.result() is None
    assert future2.result() is None


async def test_signal_external_workflow_dispatch():
    decisions = DecisionManager(asyncio.get_event_loop())

    future = decisions.signal_external_workflow(
        decision.SignalExternalWorkflowExecutionDecisionAttributes(
            domain="test-domain",
            workflow_execution=WorkflowExecution(workflow_id="child-wf-1", run_id=""),
            signal_name="my_signal",
            child_workflow_only=True,
        )
    )

    decisions.handle_history_event(signal_initiated(1, signal_id="0"))
    decisions.handle_history_event(signal_completed(2, initiated_event_id=1))

    assert future.done() is True
    assert future.result() is None


async def test_signal_external_workflow_failed_dispatch():
    decisions = DecisionManager(asyncio.get_event_loop())

    future = decisions.signal_external_workflow(
        decision.SignalExternalWorkflowExecutionDecisionAttributes(
            domain="test-domain",
            workflow_execution=WorkflowExecution(workflow_id="child-wf-1", run_id=""),
            signal_name="my_signal",
            child_workflow_only=True,
        )
    )

    decisions.handle_history_event(signal_initiated(1, signal_id="0"))
    decisions.handle_history_event(signal_failed(2, initiated_event_id=1))

    assert future.done() is True
    with pytest.raises(SignalExternalWorkflowFailed):
        future.result()


def signal_initiated(event_id: int, signal_id: str) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        signal_external_workflow_execution_initiated_event_attributes=history.SignalExternalWorkflowExecutionInitiatedEventAttributes(
            control=signal_id.encode("utf-8"),
            signal_name="my_signal",
        ),
    )


def signal_completed(event_id: int, initiated_event_id: int) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        external_workflow_execution_signaled_event_attributes=history.ExternalWorkflowExecutionSignaledEventAttributes(
            initiated_event_id=initiated_event_id,
        ),
    )


def signal_failed(event_id: int, initiated_event_id: int) -> history.HistoryEvent:
    return history.HistoryEvent(
        event_id=event_id,
        signal_external_workflow_execution_failed_event_attributes=history.SignalExternalWorkflowExecutionFailedEventAttributes(
            initiated_event_id=initiated_event_id,
        ),
    )
