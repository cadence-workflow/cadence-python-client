from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionState,
    DecisionFuture,
    DecisionType,
    DecisionId,
    BaseDecisionStateMachine,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence._internal.workflow.statemachine.nondeterminism import (
    record_immediate_cancel,
)
from cadence.api.v1 import decision, history

timer_events = EventDispatcher("timer_id")


class TimerStateMachine(BaseDecisionStateMachine):
    request: decision.StartTimerDecisionAttributes
    completed: DecisionFuture[None]

    def __init__(
        self,
        request: decision.StartTimerDecisionAttributes,
        completed: DecisionFuture[None],
    ) -> None:
        super().__init__()
        self.request = request
        self.completed = completed

    def get_id(self) -> DecisionId:
        return DecisionId(DecisionType.TIMER, self.request.timer_id)

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(start_timer_decision_attributes=self.request)
        if self.state is DecisionState.CANCELED_AFTER_REQUESTED:
            return record_immediate_cancel(self.request)
        if self.state is DecisionState.CANCELED_AFTER_RECORDED:
            return decision.Decision(
                cancel_timer_decision_attributes=decision.CancelTimerDecisionAttributes(
                    timer_id=self.request.timer_id,
                )
            )
        return None

    def request_cancel(self) -> bool:
        if self.state is DecisionState.REQUESTED:
            self._transition(DecisionState.CANCELED_AFTER_REQUESTED)
            self.completed.force_cancel()
            return True

        if self.state is DecisionState.RECORDED:
            self._transition(DecisionState.CANCELED_AFTER_RECORDED)
            self.completed.force_cancel()
            return True

        return False

    @timer_events.event()
    def handle_started(self, _: history.TimerStartedEventAttributes) -> None:
        self._transition(DecisionState.RECORDED)

    @timer_events.event()
    def handle_fired(self, _: history.TimerFiredEventAttributes) -> None:
        self._transition(DecisionState.COMPLETED)
        self.completed.set_result(None)

    @timer_events.event()
    def handle_canceled(self, _: history.TimerCanceledEventAttributes) -> None:
        # Timers resolve immediately regardless of the outcome of the cancellation
        self._transition(DecisionState.COMPLETED)

    @timer_events.event()
    def handle_cancel_failed(self, _: history.CancelTimerFailedEventAttributes) -> None:
        # This leaves the timer in a likely invalid state, but matches the other clients.
        # The only way for timer cancellation to fail is if the timer ID isn't known, so this
        # can't really happen in the first place.
        self._transition(DecisionState.RECORDED)
