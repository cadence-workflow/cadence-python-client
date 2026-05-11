from __future__ import annotations

from cadence._internal.workflow.statemachine.decision_state_machine import (
    BaseDecisionStateMachine,
    DecisionFuture,
    DecisionId,
    DecisionState,
    DecisionType,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence._internal.workflow.statemachine.nondeterminism import (
    record_immediate_cancel,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload, WorkflowExecution
from cadence.error import (
    ChildWorkflowExecutionCanceled,
    ChildWorkflowExecutionFailed,
    ChildWorkflowExecutionTerminated,
    ChildWorkflowExecutionTimedOut,
    StartChildWorkflowExecutionFailed,
)

child_workflow_events = EventDispatcher("initiated_event_id")


class ChildWorkflowExecutionStateMachine(BaseDecisionStateMachine):
    """State machine for StartChildWorkflowExecution and child close events."""

    request: decision.StartChildWorkflowExecutionDecisionAttributes
    execution: DecisionFuture[WorkflowExecution]
    result: DecisionFuture[Payload]
    _run_id: str | None

    def __init__(
        self,
        request: decision.StartChildWorkflowExecutionDecisionAttributes,
        execution: DecisionFuture[WorkflowExecution],
        result: DecisionFuture[Payload],
    ) -> None:
        super().__init__()
        self.request = request
        self.execution = execution
        self.result = result
        self._run_id = None

    def get_id(self) -> DecisionId:
        return DecisionId(DecisionType.CHILD_WORKFLOW, self.request.workflow_id)

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(
                start_child_workflow_execution_decision_attributes=self.request
            )
        if self.state is DecisionState.CANCELED_AFTER_REQUESTED:
            return record_immediate_cancel(self.request)
        if self.state in (
            DecisionState.CANCELED_AFTER_RECORDED,
            DecisionState.CANCELED_AFTER_STARTED,
        ):
            return decision.Decision(
                request_cancel_external_workflow_execution_decision_attributes=decision.RequestCancelExternalWorkflowExecutionDecisionAttributes(
                    domain=self.request.domain,
                    workflow_execution=WorkflowExecution(
                        workflow_id=self.request.workflow_id,
                        run_id=self._run_id or "",
                    ),
                    child_workflow_only=True,
                )
            )
        return None

    def request_cancel(self) -> bool:
        if self.state is DecisionState.REQUESTED:
            self._transition(DecisionState.CANCELED_AFTER_REQUESTED)
            self.execution.force_cancel()
            self.result.force_cancel()
            return True

        if self.state is DecisionState.RECORDED:
            self._transition(DecisionState.CANCELED_AFTER_RECORDED)
            self.execution.force_cancel()
            return True

        if self.state is DecisionState.STARTED:
            self._transition(DecisionState.CANCELED_AFTER_STARTED)
            return True

        return False

    @child_workflow_events.event("workflow_id", event_id_is_alias=True)
    def handle_initiated(
        self, _: history.StartChildWorkflowExecutionInitiatedEventAttributes
    ) -> None:
        self._transition(DecisionState.RECORDED)

    @child_workflow_events.event()
    def handle_initiation_failed(
        self, event: history.StartChildWorkflowExecutionFailedEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        exc = StartChildWorkflowExecutionFailed(
            f"start child failed: {event.cause}",
            cause=event.cause,
            workflow_id=event.workflow_id,
        )
        self.execution.set_exception(exc)
        self.result.set_exception(exc)

    @child_workflow_events.event()
    def handle_started(
        self, event: history.ChildWorkflowExecutionStartedEventAttributes
    ) -> None:
        self._transition(DecisionState.STARTED)
        self._run_id = event.workflow_execution.run_id
        self.execution.set_result(event.workflow_execution)

    @child_workflow_events.event()
    def handle_completed(
        self, event: history.ChildWorkflowExecutionCompletedEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.result.set_result(event.result)

    @child_workflow_events.event()
    def handle_failed(
        self, event: history.ChildWorkflowExecutionFailedEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.result.set_exception(
            ChildWorkflowExecutionFailed(
                event.failure.reason,
                failure=event.failure,
            )
        )

    @child_workflow_events.event()
    def handle_canceled(
        self, event: history.ChildWorkflowExecutionCanceledEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.result.set_exception(
            ChildWorkflowExecutionCanceled(
                "child workflow canceled", details=event.details
            )
        )

    @child_workflow_events.event()
    def handle_timed_out(
        self, event: history.ChildWorkflowExecutionTimedOutEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.result.set_exception(
            ChildWorkflowExecutionTimedOut(
                f"child workflow timed out: {event.timeout_type}",
                timeout_type=int(event.timeout_type),
            )
        )

    @child_workflow_events.event()
    def handle_terminated(
        self, event: history.ChildWorkflowExecutionTerminatedEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
        self.result.set_exception(ChildWorkflowExecutionTerminated())

    # RequestCancelExternalWorkflowExecution events reference the child workflow by
    # workflow_execution.workflow_id (a nested field), not by a bare string id.
    # The dispatcher resolves dotted paths, so "workflow_execution.workflow_id" extracts
    # the correct key for the alias lookup.  event_id_is_alias=True registers this event's
    # ID so that the subsequent handle_cancel_failed can look it up via initiated_event_id.
    @child_workflow_events.event(
        "workflow_execution.workflow_id", event_id_is_alias=True
    )
    def handle_cancel_initiated(
        self, _: history.RequestCancelExternalWorkflowExecutionInitiatedEventAttributes
    ) -> None:
        self._transition(DecisionState.CANCELLATION_RECORDED)

    @child_workflow_events.event()
    def handle_cancel_failed(
        self, _: history.RequestCancelExternalWorkflowExecutionFailedEventAttributes
    ) -> None:
        self._transition(DecisionState.STARTED)
