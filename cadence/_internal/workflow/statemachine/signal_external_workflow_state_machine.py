from __future__ import annotations

from typing import Any

from cadence._internal.workflow.statemachine.decision_state_machine import (
    BaseDecisionStateMachine,
    DecisionFuture,
    DecisionId,
    DecisionState,
    DecisionType,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence.api.v1 import decision, history

signal_external_events = EventDispatcher("initiated_event_id")


class SignalExternalWorkflowFailed(Exception):
    def __init__(self, message: str, cause: Any) -> None:
        super().__init__(message)
        self.cause = cause


class SignalExternalWorkflowStateMachine(BaseDecisionStateMachine):
    """State machine for SignalExternalWorkflowExecution and signal events."""

    request: decision.SignalExternalWorkflowExecutionDecisionAttributes
    completed: DecisionFuture[None]
    _signal_id: str

    def __init__(
        self,
        request: decision.SignalExternalWorkflowExecutionDecisionAttributes,
        completed: DecisionFuture[None],
        signal_id: str,
    ) -> None:
        super().__init__()
        self.request = request
        self.completed = completed
        self._signal_id = signal_id

    def get_id(self) -> DecisionId:
        return DecisionId(DecisionType.SIGNAL, self._signal_id)

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(
                signal_external_workflow_execution_decision_attributes=self.request
            )
        return None

    def request_cancel(self) -> bool:
        return False

    @signal_external_events.event(id_attr="control", event_id_is_alias=True)
    def handle_initiated(
        self,
        _: history.SignalExternalWorkflowExecutionInitiatedEventAttributes,
    ) -> None:
        self._transition(DecisionState.RECORDED)

    @signal_external_events.event()
    def handle_completed(
        self,
        _: history.ExternalWorkflowExecutionSignaledEventAttributes,
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.completed.set_result(None)

    @signal_external_events.event()
    def handle_failed(
        self,
        event: history.SignalExternalWorkflowExecutionFailedEventAttributes,
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.completed.set_exception(
            SignalExternalWorkflowFailed(
                f"signal external workflow failed: {event.cause}",
                cause=event.cause,
            )
        )
