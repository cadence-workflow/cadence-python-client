import pytest

from typing import Any

from cadence._internal.workflow.statemachine.cancellation import to_marker
from cadence._internal.workflow.statemachine.completion_state_machine import (
    COMPLETION_ID,
)
from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionId,
    DecisionType,
)
from cadence._internal.workflow.statemachine.marker_state_machine import (
    encode_marker_details,
)
from cadence._internal.workflow.statemachine.nondeterminism import (
    to_expectation,
    Expectation,
    CANCEL,
    DeterminismTracker,
    NonDeterminismError,
)
from cadence.api.v1 import common, decision, history


class TestDeterminismTracker:
    def test_single_expectation_met(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        tracker.validate_action(
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0", activity_type=common.ActivityType(name="act")
            )
        )
        tracker.complete_replay()

    def test_multiple_expectation_met(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=2,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="1", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        tracker.validate_action(
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0", activity_type=common.ActivityType(name="act")
            )
        )
        tracker.validate_action(
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="1", activity_type=common.ActivityType(name="act")
            )
        )
        tracker.complete_replay()

    def test_cancel_marker_met(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                    marker_name="Cancel_0",
                    details=to_marker(
                        DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
                    ).details,
                )
            )
        )
        tracker.validate_action(
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0", activity_type=common.ActivityType(name="act")
            )
        )
        tracker.validate_cancel(DecisionId(DecisionType.ACTIVITY, "0"))
        tracker.complete_replay()

    def test_cancel_schedule_reorder_allowed(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="1", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=2,
                marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                    marker_name="Cancel_0",
                    details=to_marker(
                        DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
                    ).details,
                ),
            )
        )
        # The order doesn't match the history events, because the cancel marker will be at the time of cancellation, not
        # scheduling
        tracker.validate_action(
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0", activity_type=common.ActivityType(name="act")
            )
        )
        tracker.validate_action(
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="1", activity_type=common.ActivityType(name="act")
            )
        )
        tracker.validate_cancel(DecisionId(DecisionType.ACTIVITY, "0"))
        tracker.complete_replay()

    def test_cancel_expected_nondeterminism(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                    marker_name="Cancel_0",
                    details=to_marker(
                        DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
                    ).details,
                )
            )
        )
        tracker.validate_action(
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0", activity_type=common.ActivityType(name="act")
            )
        )
        with pytest.raises(NonDeterminismError) as excinfo:
            tracker.complete_replay()

        assert excinfo.value.expected == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), CANCEL
        )
        assert excinfo.value.actual is None

    def test_cancel_early_nondeterminism(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="1", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=2,
                marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                    marker_name="Cancel_0",
                    details=to_marker(
                        DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
                    ).details,
                ),
            )
        )
        tracker.validate_action(
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0", activity_type=common.ActivityType(name="act")
            )
        )
        # Based on the history events, we know that activityID 1 needed to be scheduled before this is cancelled
        with pytest.raises(NonDeterminismError) as excinfo:
            tracker.validate_cancel(DecisionId(DecisionType.ACTIVITY, "0"))

        assert excinfo.value.expected == Expectation(
            DecisionId(DecisionType.ACTIVITY, "1"), {"activity_type": "act"}
        )
        assert excinfo.value.actual == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), CANCEL
        )

    def test_cancel_props_changed_nondeterminism(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                    marker_name="Cancel_0",
                    details=to_marker(
                        DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
                    ).details,
                )
            )
        )
        with pytest.raises(NonDeterminismError) as excinfo:
            tracker.validate_action(
                decision.ScheduleActivityTaskDecisionAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="different")
                )
            )

        assert excinfo.value.expected == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
        )
        assert excinfo.value.actual == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "different"}
        )

    def test_nothing_expected_nondeterminism(self):
        tracker = DeterminismTracker()
        with pytest.raises(NonDeterminismError) as excinfo:
            tracker.validate_action(
                decision.ScheduleActivityTaskDecisionAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="act")
                )
            )

        assert excinfo.value.expected is None
        assert excinfo.value.actual == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
        )

    def test_expectation_not_met_nondeterminism(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        with pytest.raises(NonDeterminismError) as excinfo:
            tracker.complete_replay()

        assert excinfo.value.expected == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
        )
        assert excinfo.value.actual is None

    def test_wrong_type_expected_nondeterminism(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        with pytest.raises(NonDeterminismError) as excinfo:
            tracker.validate_action(decision.StartTimerDecisionAttributes(timer_id="0"))

        assert excinfo.value.expected == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
        )
        assert excinfo.value.actual == Expectation(
            DecisionId(DecisionType.TIMER, "0"), {}
        )

    def test_property_change_nondeterminism(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        with pytest.raises(NonDeterminismError) as excinfo:
            tracker.validate_action(
                decision.ScheduleActivityTaskDecisionAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="actual")
                )
            )

        assert excinfo.value.expected == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
        )
        assert excinfo.value.actual == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "actual"}
        )

    def test_signal_external_workflow_failed_event_matches_decision(self):
        # If the server records a SignalExternalWorkflowExecutionFailed event (instead of
        # Initiated), replay must still validate the signal decision successfully.
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                signal_external_workflow_execution_failed_event_attributes=history.SignalExternalWorkflowExecutionFailedEventAttributes(
                    control=b"0"
                ),
            )
        )
        tracker.validate_action(
            decision.SignalExternalWorkflowExecutionDecisionAttributes(
                control=b"0", signal_name="my-signal"
            )
        )
        tracker.complete_replay()

    def test_expectations_out_of_order_nondeterminism(self):
        tracker = DeterminismTracker()
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="0", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=2,
                activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                    activity_id="1", activity_type=common.ActivityType(name="act")
                ),
            )
        )
        with pytest.raises(NonDeterminismError) as excinfo:
            tracker.validate_action(
                decision.ScheduleActivityTaskDecisionAttributes(
                    activity_id="1", activity_type=common.ActivityType(name="act")
                )
            )

        assert excinfo.value.expected == Expectation(
            DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
        )
        assert excinfo.value.actual == Expectation(
            DecisionId(DecisionType.ACTIVITY, "1"), {"activity_type": "act"}
        )

    def test_marker_expectation_does_not_carry_details(self):
        # Details are handled by DecisionManager._recorded_marker_details, not Expectation.
        tracker = DeterminismTracker()
        encoded = encode_marker_details("0", b"history-value")
        recorded = history.MarkerRecordedEventAttributes(
            marker_name="SideEffect",
            details=common.Payload(data=encoded),
        )
        requested = decision.RecordMarkerDecisionAttributes(
            marker_name="SideEffect",
            details=common.Payload(data=encoded),
        )
        tracker.add_expectation(
            history.HistoryEvent(
                event_id=1,
                marker_recorded_event_attributes=recorded,
            )
        )

        expectation = tracker.validate_action(requested)

        assert expectation == Expectation(
            DecisionId(DecisionType.MARKER, "SideEffect_0"),
            {"marker_name": "SideEffect"},
        )
        assert "details" not in expectation.properties
        tracker.complete_replay()


@pytest.mark.parametrize(
    "attrs,expected",
    [
        (
            history.TimerStartedEventAttributes(timer_id="0"),
            Expectation(DecisionId(DecisionType.TIMER, "0"), {}),
        ),
        (
            decision.StartTimerDecisionAttributes(timer_id="0"),
            Expectation(DecisionId(DecisionType.TIMER, "0"), {}),
        ),
        # Timer canceled
        (
            history.TimerCanceledEventAttributes(timer_id="0"),
            Expectation(DecisionId(DecisionType.TIMER, "0"), CANCEL),
        ),
        (
            decision.CancelTimerDecisionAttributes(timer_id="0"),
            Expectation(DecisionId(DecisionType.TIMER, "0"), CANCEL),
        ),
        (
            history.CancelTimerFailedEventAttributes(timer_id="0"),
            Expectation(DecisionId(DecisionType.TIMER, "0"), CANCEL),
        ),
        # Activity scheduled
        (
            decision.ScheduleActivityTaskDecisionAttributes(
                activity_id="0", activity_type=common.ActivityType(name="act")
            ),
            Expectation(
                DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
            ),
        ),
        (
            history.ActivityTaskScheduledEventAttributes(
                activity_id="0", activity_type=common.ActivityType(name="act")
            ),
            Expectation(
                DecisionId(DecisionType.ACTIVITY, "0"), {"activity_type": "act"}
            ),
        ),
        # Activity cancel requested
        (
            decision.RequestCancelActivityTaskDecisionAttributes(activity_id="0"),
            Expectation(DecisionId(DecisionType.ACTIVITY, "0"), CANCEL),
        ),
        (
            history.ActivityTaskCancelRequestedEventAttributes(activity_id="0"),
            Expectation(DecisionId(DecisionType.ACTIVITY, "0"), CANCEL),
        ),
        # Child workflow start
        (
            decision.StartChildWorkflowExecutionDecisionAttributes(
                workflow_id="0",
                workflow_type=common.WorkflowType(name="wf"),
            ),
            Expectation(
                DecisionId(DecisionType.CHILD_WORKFLOW, "0"),
                {"workflow_type": "wf"},
            ),
        ),
        (
            history.StartChildWorkflowExecutionInitiatedEventAttributes(
                workflow_id="0",
                workflow_type=common.WorkflowType(name="wf"),
            ),
            Expectation(
                DecisionId(DecisionType.CHILD_WORKFLOW, "0"),
                {"workflow_type": "wf"},
            ),
        ),
        (
            history.StartChildWorkflowExecutionFailedEventAttributes(
                workflow_id="0",
                workflow_type=common.WorkflowType(name="wf"),
            ),
            Expectation(
                DecisionId(DecisionType.CHILD_WORKFLOW, "0"),
                {"workflow_type": "wf"},
            ),
        ),
        # Child workflow cancel requested
        (
            decision.RequestCancelExternalWorkflowExecutionDecisionAttributes(
                workflow_execution=common.WorkflowExecution(workflow_id="0"),
            ),
            Expectation(DecisionId(DecisionType.CHILD_WORKFLOW, "0"), CANCEL),
        ),
        (
            history.RequestCancelExternalWorkflowExecutionInitiatedEventAttributes(
                workflow_execution=common.WorkflowExecution(workflow_id="0"),
            ),
            Expectation(DecisionId(DecisionType.CHILD_WORKFLOW, "0"), CANCEL),
        ),
        (
            history.RequestCancelExternalWorkflowExecutionFailedEventAttributes(
                workflow_execution=common.WorkflowExecution(workflow_id="0"),
            ),
            Expectation(DecisionId(DecisionType.CHILD_WORKFLOW, "0"), CANCEL),
        ),
        # Signal external workflow
        (
            decision.SignalExternalWorkflowExecutionDecisionAttributes(
                control=b"0", signal_name="my-signal"
            ),
            Expectation(
                DecisionId(DecisionType.SIGNAL, "0"), {"signal_name": "my-signal"}
            ),
        ),
        (
            history.SignalExternalWorkflowExecutionInitiatedEventAttributes(
                control=b"0", signal_name="my-signal"
            ),
            Expectation(
                DecisionId(DecisionType.SIGNAL, "0"), {"signal_name": "my-signal"}
            ),
        ),
        (
            history.SignalExternalWorkflowExecutionFailedEventAttributes(control=b"0"),
            Expectation(DecisionId(DecisionType.SIGNAL, "0"), {}),
        ),
        # Workflow complete
        (
            decision.CompleteWorkflowExecutionDecisionAttributes(),
            Expectation(COMPLETION_ID, {"success": True}),
        ),
        (
            history.WorkflowExecutionCompletedEventAttributes(),
            Expectation(COMPLETION_ID, {"success": True}),
        ),
        # Workflow fail
        (
            decision.FailWorkflowExecutionDecisionAttributes(),
            Expectation(COMPLETION_ID, {"success": False}),
        ),
        (
            history.WorkflowExecutionFailedEventAttributes(),
            Expectation(COMPLETION_ID, {"success": False}),
        ),
        # Unknown type returns None
        ("not_a_supported_type", None),
        # Marker: SideEffect decision-side
        (
            decision.RecordMarkerDecisionAttributes(
                marker_name="SideEffect",
                details=common.Payload(data=encode_marker_details("0", b"")),
            ),
            Expectation(
                DecisionId(DecisionType.MARKER, "SideEffect_0"),
                {"marker_name": "SideEffect"},
            ),
        ),
        # Marker: SideEffect history-side (no details in properties)
        (
            history.MarkerRecordedEventAttributes(
                marker_name="SideEffect",
                details=common.Payload(data=encode_marker_details("0", b"value")),
            ),
            Expectation(
                DecisionId(DecisionType.MARKER, "SideEffect_0"),
                {"marker_name": "SideEffect"},
            ),
        ),
        # Marker: Version decision-side → None (exempt)
        (
            decision.RecordMarkerDecisionAttributes(
                marker_name="Version",
                details=common.Payload(data=encode_marker_details("0", b"")),
            ),
            None,
        ),
        # Marker: Version history-side → None (exempt)
        (
            history.MarkerRecordedEventAttributes(
                marker_name="Version",
                details=common.Payload(data=encode_marker_details("0", b"")),
            ),
            None,
        ),
        # Marker: no encoded context_id → None
        (
            decision.RecordMarkerDecisionAttributes(
                marker_name="SideEffect",
                details=common.Payload(data=b"raw-no-encoding"),
            ),
            None,
        ),
    ],
)
def test_to_expectation(attrs: Any, expected: Expectation):
    result = to_expectation(attrs)
    assert result == expected
