from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionState,
    DecisionType,
    DecisionId,
    DecisionFuture,
    BaseDecisionStateMachine,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence._internal.workflow.statemachine.nondeterminism import (
    record_immediate_cancel,
)
from cadence._internal.workflow.deterministic_event_loop import (
    FatalDecisionError,
    fail_decision,
)
from cadence._internal.failure import activity_failed_error, activity_timed_out_error
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DataConverter

activity_events = EventDispatcher("scheduled_event_id")


class ActivityStateMachine(BaseDecisionStateMachine):
    request: decision.ScheduleActivityTaskDecisionAttributes
    completed: DecisionFuture[Payload]

    def __init__(
        self,
        request: decision.ScheduleActivityTaskDecisionAttributes,
        completed: DecisionFuture[Payload],
        data_converter: DataConverter,
    ) -> None:
        super().__init__()
        self.request = request
        self.completed = completed
        self._data_converter = data_converter

    def get_id(self) -> DecisionId:
        return DecisionId(DecisionType.ACTIVITY, self.request.activity_id)

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(
                schedule_activity_task_decision_attributes=self.request
            )
        if self.state is DecisionState.CANCELED_AFTER_REQUESTED:
            return record_immediate_cancel(self.request)

        if self.state is DecisionState.CANCELED_AFTER_RECORDED:
            return decision.Decision(
                request_cancel_activity_task_decision_attributes=decision.RequestCancelActivityTaskDecisionAttributes(
                    activity_id=self.request.activity_id,
                )
            )

        return None

    def request_cancel(self, message: str | None = None) -> bool:
        if self.state is DecisionState.REQUESTED:
            self._transition(DecisionState.CANCELED_AFTER_REQUESTED)
            self._force_cancel(message)
            return True

        if self.state is DecisionState.RECORDED:
            self._transition(DecisionState.CANCELED_AFTER_RECORDED)
            return True

        return False

    def _force_cancel(self, message: str | None = None) -> None:
        if not self.completed.done():
            self.completed.force_cancel(message)

    @activity_events.event(id_attr="activity_id", event_id_is_alias=True)
    def handle_scheduled(self, _: history.ActivityTaskScheduledEventAttributes) -> None:
        self._transition(DecisionState.RECORDED)

    @activity_events.event()
    def handle_started(self, _: history.ActivityTaskStartedEventAttributes) -> None:
        # Started doesn't actually do anything in the Go client.
        # The workflow can't observe it, and it doesn't impact cancellation
        # self._transition(DecisionState.STARTED)
        pass

    @activity_events.event()
    def handle_completed(
        self, event: history.ActivityTaskCompletedEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self._resolve(self.completed, result=event.result)

    @activity_events.event()
    def handle_failed(self, event: history.ActivityTaskFailedEventAttributes) -> None:
        self._transition(DecisionState.COMPLETED)
        self._resolve(
            self.completed,
            exc=activity_failed_error(event, self.request, self._data_converter),
        )

    @activity_events.event()
    def handle_timeout(
        self, event: history.ActivityTaskTimedOutEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self._resolve(
            self.completed,
            exc=activity_timed_out_error(event, self.request, self._data_converter),
        )

    @activity_events.event()
    def handle_canceled(self, _: history.ActivityTaskCanceledEventAttributes) -> None:
        # An activity should only report a cancellation that the workflow
        # requested. Cadence doesn't enforce this, but the Go and Java clients
        # fail the decision task when it happens, so this does too.
        if self.state not in (
            DecisionState.CANCELED_AFTER_RECORDED,
            DecisionState.CANCELLATION_RECORDED,
        ):
            fail_decision(
                FatalDecisionError(
                    f"activity {self.request.activity_id!r} canceled without a "
                    "cancellation request"
                )
            )
        self._transition(DecisionState.COMPLETED)
        self._force_cancel()

    @activity_events.event("activity_id")
    def handle_cancel_requested(
        self, _: history.ActivityTaskCancelRequestedEventAttributes
    ) -> None:
        self._transition(DecisionState.CANCELLATION_RECORDED)

    @activity_events.event("activity_id")
    def handle_cancel_failed(
        self, _: history.RequestCancelActivityTaskFailedEventAttributes
    ) -> None:
        self._transition(DecisionState.RECORDED)
