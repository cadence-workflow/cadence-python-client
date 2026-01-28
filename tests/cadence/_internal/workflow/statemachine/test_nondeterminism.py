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
    ],
)
def test_to_expectation(attrs: Any, expected: Expectation):
    result = to_expectation(attrs)
    assert result == expected
