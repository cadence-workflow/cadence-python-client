
from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionStateMachine,
    DecisionState,
    DecisionType,
    DecisionId,
    MachineFuture,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload
from cadence.error import ActivityFailure

activity_events = EventDispatcher("scheduled_event_id")


class ActivityStateMachine(DecisionStateMachine):
    request: decision.ScheduleActivityTaskDecisionAttributes
    state: DecisionState
    completed: MachineFuture[Payload]

    def __init__(
        self,
        request: decision.ScheduleActivityTaskDecisionAttributes,
        completed: MachineFuture[Payload],
    ) -> None:
        self.request = request
        self.state = DecisionState.CREATED
        self.completed = completed

    def get_id(self) -> DecisionId:
        return DecisionId(DecisionType.ACTIVITY, self.request.activity_id)

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.CREATED:
            return decision.Decision(
                schedule_activity_task_decision_attributes=self.request
            )

        if self.state is DecisionState.CANCELED_AFTER_INITIATED:
            return decision.Decision(
                request_cancel_activity_task_decision_attributes=decision.RequestCancelActivityTaskDecisionAttributes(
                    activity_id=self.request.activity_id,
                )
            )

        return None

    def request_cancel(self) -> bool:
        if self.state is DecisionState.CREATED:
            self._transition(DecisionState.COMPLETED)
            self.completed.force_cancel()
            return True

        if self.state is DecisionState.INITIATED:
            self._transition(DecisionState.CANCELED_AFTER_INITIATED)
            return True

        return False

    def _transition(self, to: DecisionState) -> None:
        # TODO: Add validation on transitions, maybe track previous state like the other clients
        # if self.state not in allowed_from:
        #    raise RuntimeError(f"unable to transition to {to} from {self.state}")
        self.state = to

    @activity_events.event(id_attr="activity_id", event_id_is_alias=True)
    def handle_scheduled(self, _: history.ActivityTaskScheduledEventAttributes) -> None:
        self._transition(DecisionState.INITIATED)

    @activity_events.event()
    def handle_started(self, event: history.ActivityTaskStartedEventAttributes) -> None:
        # Started doesn't actually do anything in the Go client.
        # The workflow can't observe it, and it doesn't impact cancellation
        # self._transition(DecisionState.STARTED)
        pass

    @activity_events.event()
    def handle_completed(
        self, event: history.ActivityTaskCompletedEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.completed.set_result(event.result)

    @activity_events.event()
    def handle_failed(self, event: history.ActivityTaskFailedEventAttributes) -> None:
        self._transition(DecisionState.COMPLETED)
        self.completed.set_exception(ActivityFailure(event.failure.reason))

    @activity_events.event()
    def handle_timeout(
        self, event: history.ActivityTaskTimedOutEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.completed.set_exception(ActivityFailure(event.details.data.decode()))

    @activity_events.event()
    def handle_canceled(
        self, event: history.ActivityTaskCanceledEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.completed.force_cancel(event.details.data.decode())

    @activity_events.event("activity_id")
    def handle_cancel_requested(
        self, _: history.ActivityTaskCancelRequestedEventAttributes
    ) -> None:
        self._transition(DecisionState.CANCELLATION_DECISION_SENT)

    @activity_events.event("activity_id")
    def handle_cancel_failed(
        self, _: history.RequestCancelActivityTaskFailedEventAttributes
    ) -> None:
        self._transition(DecisionState.INITIATED)
