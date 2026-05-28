import pytest

from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionFuture,
    DecisionState,
)
from cadence._internal.workflow.statemachine.signal_external_workflow_state_machine import (
    SignalExternalWorkflowFailed,
    SignalExternalWorkflowStateMachine,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import WorkflowExecution

SIGNAL_ID = "0"
DOMAIN = "test-domain"


def make_sm() -> tuple[SignalExternalWorkflowStateMachine, DecisionFuture[None]]:
    attrs = decision.SignalExternalWorkflowExecutionDecisionAttributes(
        domain=DOMAIN,
        workflow_execution=WorkflowExecution(
            workflow_id="child-wf-1", run_id=""
        ),
        signal_name="my_signal",
        child_workflow_only=True,
        control=SIGNAL_ID.encode("utf-8"),
    )
    completed: DecisionFuture[None] = DecisionFuture()
    sm = SignalExternalWorkflowStateMachine(attrs, completed, SIGNAL_ID)
    return sm, completed


async def test_initial_state():
    sm, completed = make_sm()

    assert sm.state is DecisionState.REQUESTED
    assert completed.done() is False
    assert sm.get_decision() == decision.Decision(
        signal_external_workflow_execution_decision_attributes=sm.request
    )


async def test_cancel_returns_false():
    sm, _completed = make_sm()

    assert sm.request_cancel() is False
    assert sm.state is DecisionState.REQUESTED


async def test_initiated_transitions_to_recorded():
    sm, completed = make_sm()

    sm.handle_initiated(
        history.SignalExternalWorkflowExecutionInitiatedEventAttributes(
            control=SIGNAL_ID.encode("utf-8"),
        )
    )

    assert sm.state is DecisionState.RECORDED
    assert completed.done() is False
    assert sm.get_decision() is None


async def test_completed_resolves_future():
    sm, completed = make_sm()

    sm.handle_initiated(
        history.SignalExternalWorkflowExecutionInitiatedEventAttributes(
            control=SIGNAL_ID.encode("utf-8"),
        )
    )
    sm.handle_completed(
        history.ExternalWorkflowExecutionSignaledEventAttributes(
            initiated_event_id=1,
        )
    )

    assert sm.state is DecisionState.COMPLETED
    assert completed.done() is True
    assert completed.result() is None
    assert sm.get_decision() is None


async def test_failed_rejects_future():
    sm, completed = make_sm()

    sm.handle_initiated(
        history.SignalExternalWorkflowExecutionInitiatedEventAttributes(
            control=SIGNAL_ID.encode("utf-8"),
        )
    )
    sm.handle_failed(
        history.SignalExternalWorkflowExecutionFailedEventAttributes(
            initiated_event_id=1,
        )
    )

    assert sm.state is DecisionState.COMPLETED
    assert completed.done() is True
    with pytest.raises(SignalExternalWorkflowFailed, match="signal external workflow failed"):
        completed.result()
