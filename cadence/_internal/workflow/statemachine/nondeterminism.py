from dataclasses import dataclass
from functools import singledispatch
from typing import Any, OrderedDict, Dict, List, Never

from cadence._internal.workflow.deterministic_event_loop import FatalDecisionError
from cadence._internal.workflow.statemachine.cancellation import (
    is_immediate_cancel,
    from_marker,
    to_marker,
)
from cadence._internal.workflow.statemachine.completion_state_machine import (
    COMPLETION_ID,
)
from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionId,
    DecisionType,
)
from cadence.api.v1 import decision, history


@dataclass(frozen=True)
class Expectation:
    decision_id: DecisionId
    properties: Dict[str, Any]
    event_id: int | None = None

    def with_event_id(self, event_id: int) -> "Expectation":
        return Expectation(self.decision_id, self.properties, event_id)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Expectation):
            return False

        if self.decision_id != other.decision_id:
            return False

        # Only compare the keys that are present in both. This allows for adding/removing
        # the properties that we consider for a given type. These keys always come from
        # to_expectation, so it's up to us to set the key even for values of None.
        common_keys = set(self.properties.keys()) & set(other.properties.keys())
        for key in common_keys:
            if self.properties.get(key) != other.properties.get(key):
                return False

        return True

    def __ne__(self, other: Any) -> bool:
        return not (self == other)

    def __str__(self) -> str:
        pretty_attr = (
            ({"event_id": self.event_id} | self.properties)
            if self.event_id
            else self.properties
        )
        return f"{self.decision_id.decision_type.name}({pretty_attr})"


CANCEL = {"canceled": True}


class NonDeterminismError(FatalDecisionError):
    def __init__(
        self, expected: Expectation | None, actual: Expectation | None
    ) -> None:
        super().__init__(f"Expected: {expected}, actual: {actual}", expected, actual)
        self.expected = expected
        self.actual = actual


class DeterminismTracker:
    def __init__(self) -> None:
        self._expectations: OrderedDict[DecisionId, List[Expectation]] = OrderedDict()
        self._failed = False

    def add_expectation(self, event: history.HistoryEvent) -> None:
        # Immediate cancellation is the only case where we have more than one Expectation
        if event.marker_recorded_event_attributes is not None and is_immediate_cancel(
            event.marker_recorded_event_attributes
        ):
            decision_id, props = from_marker(event.marker_recorded_event_attributes)
            to_expect = [
                # Creation
                Expectation(
                    event_id=event.event_id, decision_id=decision_id, properties=props
                ),
                # Cancellation
                Expectation(
                    event_id=event.event_id, decision_id=decision_id, properties=CANCEL
                ),
            ]
            self._add_expectations(decision_id, to_expect)
            return

        attr = event.WhichOneof("attributes")
        event_attributes = getattr(event, attr)
        expected = to_expectation(event_attributes)
        if expected is None:
            return

        # Add Event ID just to improve debugging experience
        expected = expected.with_event_id(event.event_id)

        self._add_expectations(expected.decision_id, [expected])

    def _add_expectations(
        self, decision_id: DecisionId, to_expect: List[Expectation]
    ) -> None:
        if decision_id in self._expectations:
            raise FatalDecisionError(
                f"Received duplicate expectation for {decision_id}: {self._expectations[decision_id]} and {to_expect}"
            )

        self._expectations[decision_id] = to_expect

    def validate_action(self, attributes: Any) -> None:
        props = to_expectation(attributes)
        if props is None:
            return

        self._validate_expectation(props)

    def validate_cancel(self, decision_id: DecisionId) -> None:
        # Cancellation may happen automatically, ignore it
        if self._failed:
            return
        self._validate_expectation(
            Expectation(decision_id=decision_id, properties=CANCEL)
        )

    def _validate_expectation(self, actual: Expectation) -> None:
        if not self._expectations:
            self._fail(None, actual)

        next_expectation = self._next_expectation()

        # This will catch most non-determinism, since changing things around in the Workflow will probably make
        # the IDs no longer line up correctly
        upcoming = self._expectations.get(actual.decision_id)
        if upcoming is None:
            self._fail(next_expectation, actual)

        # Only enforce the order if this is the final operation.
        # When we create a decision and cancel it within the same task we only append a single event to the
        # history (a marker) to indicate that it's cancelled. We don't know when it was actually scheduled.
        # For example:
        # Schedule A
        # Schedule B
        # Cancel A
        #
        # Will have a history of:
        # Schedule B
        # Cancel A
        #
        # We will expect:
        # B: [Schedule]
        # A: [Schedule, Cancel]
        if len(upcoming) == 1:
            # Using the above example, If they rewrote it to be:
            # Schedula A
            # Cancel A
            # Schedule B
            # All expectations would be met, but we still need to report that it's out of order.
            # If actual.decision_id == next_expectation.decision_id then upcoming[0] is next_expectation
            if actual.decision_id != next_expectation.decision_id:
                self._fail(next_expectation, actual)

            if actual == upcoming[0]:
                del self._expectations[actual.decision_id]
            else:
                self._fail(next_expectation, actual)
        else:
            next_for_decision = upcoming[0]
            if next_for_decision == actual:
                upcoming.pop(0)
            else:
                self._fail(next_expectation, actual)

    def _fail(self, expected: Expectation | None, actual: Expectation | None) -> Never:
        self._failed = True
        raise NonDeterminismError(expected, actual)

    def _next_expectation(self) -> Expectation:
        _, upcoming = next(iter(self._expectations.items()))
        return upcoming[0]

    def complete_replay(self) -> None:
        if self._expectations:
            self._fail(self._next_expectation(), None)
        self._expectations.clear()


def record_immediate_cancel(attrs: Any) -> decision.Decision:
    expectation = to_expectation(attrs)
    if expectation is None:
        raise FatalDecisionError(f"Unable to handle type: {attrs} ")
    return decision.Decision(
        record_marker_decision_attributes=to_marker(
            expectation.decision_id, expectation.properties
        )
    )


@singledispatch
def to_expectation(_) -> None | Expectation:
    # If we aren't familiar with the type don't enforce anything
    return None


# Timers - Allow duration to be changed, so enforce only that the timer is present
@to_expectation.register
def _(attrs: history.TimerStartedEventAttributes) -> Expectation:
    return Expectation(DecisionId(DecisionType.TIMER, attrs.timer_id), {})


@to_expectation.register
def _(attrs: decision.StartTimerDecisionAttributes) -> Expectation:
    return Expectation(DecisionId(DecisionType.TIMER, attrs.timer_id), {})


@to_expectation.register
def _(attrs: history.TimerCanceledEventAttributes) -> Expectation:
    return Expectation(DecisionId(DecisionType.TIMER, attrs.timer_id), CANCEL)


@to_expectation.register
def _(attrs: decision.CancelTimerDecisionAttributes) -> Expectation:
    return Expectation(DecisionId(DecisionType.TIMER, attrs.timer_id), CANCEL)


# Success isn't important, it's the attempt that matters.
# This is recorded instead of CancelTimerDecisionAttributes if it fails.
# Activities on the other hand will have both (cancel requested, then failed to cancel)
@to_expectation.register
def _(attrs: history.CancelTimerFailedEventAttributes) -> Expectation:
    return Expectation(DecisionId(DecisionType.TIMER, attrs.timer_id), CANCEL)


# Activities - Enforce the ActivityType is the same
@to_expectation.register
def _(attrs: decision.ScheduleActivityTaskDecisionAttributes) -> Expectation:
    return Expectation(
        DecisionId(DecisionType.ACTIVITY, attrs.activity_id),
        {
            "activity_type": attrs.activity_type.name,
        },
    )


@to_expectation.register
def _(attrs: history.ActivityTaskScheduledEventAttributes) -> Expectation:
    return Expectation(
        DecisionId(DecisionType.ACTIVITY, attrs.activity_id),
        {
            "activity_type": attrs.activity_type.name,
        },
    )


@to_expectation.register
def _(attrs: decision.RequestCancelActivityTaskDecisionAttributes) -> Expectation:
    return Expectation(DecisionId(DecisionType.ACTIVITY, attrs.activity_id), CANCEL)


@to_expectation.register
def _(attrs: history.ActivityTaskCancelRequestedEventAttributes) -> Expectation:
    return Expectation(DecisionId(DecisionType.ACTIVITY, attrs.activity_id), CANCEL)


# Workflow Completion - Enforce complete vs failure. Maybe we should enforce the output data?
@to_expectation.register
def _(_: decision.CompleteWorkflowExecutionDecisionAttributes) -> Expectation:
    return Expectation(
        COMPLETION_ID,
        {
            "success": True,
        },
    )


@to_expectation.register
def _(_: history.WorkflowExecutionCompletedEventAttributes) -> Expectation:
    return Expectation(
        COMPLETION_ID,
        {
            "success": True,
        },
    )


@to_expectation.register
def _(_: decision.FailWorkflowExecutionDecisionAttributes) -> Expectation:
    return Expectation(
        COMPLETION_ID,
        {
            "success": False,
        },
    )


@to_expectation.register
def _(_: history.WorkflowExecutionFailedEventAttributes) -> Expectation:
    return Expectation(
        COMPLETION_ID,
        {
            "success": False,
        },
    )
