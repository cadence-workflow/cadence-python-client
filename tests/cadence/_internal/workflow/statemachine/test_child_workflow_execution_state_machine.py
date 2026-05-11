import pytest

from cadence._internal.workflow.statemachine.child_workflow_execution_state_machine import (
    ChildWorkflowExecutionStateMachine,
)
from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionFuture,
    DecisionState,
)
from cadence._internal.workflow.statemachine.nondeterminism import (
    record_immediate_cancel,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Failure, Payload, WorkflowExecution, WorkflowType
from cadence.error import (
    ChildWorkflowExecutionCanceled,
    ChildWorkflowExecutionFailed,
    ChildWorkflowExecutionTerminated,
    ChildWorkflowExecutionTimedOut,
    StartChildWorkflowExecutionFailed,
)

### These tests have to be async because they rely on the presence of an eventloop

WF_ID = "child-wf-1"
DOMAIN = "test-domain"


def make_sm() -> tuple[
    ChildWorkflowExecutionStateMachine,
    DecisionFuture[WorkflowExecution],
    DecisionFuture[Payload],
]:
    attrs = decision.StartChildWorkflowExecutionDecisionAttributes(
        domain=DOMAIN,
        workflow_id=WF_ID,
        workflow_type=WorkflowType(name="MyWorkflow"),
    )
    execution: DecisionFuture[WorkflowExecution] = DecisionFuture()
    result: DecisionFuture[Payload] = DecisionFuture()
    sm = ChildWorkflowExecutionStateMachine(attrs, execution, result)
    return sm, execution, result


async def test_initial_state():
    sm, execution, result = make_sm()

    assert sm.state is DecisionState.REQUESTED
    assert execution.done() is False
    assert result.done() is False
    assert sm.get_decision() == decision.Decision(
        start_child_workflow_execution_decision_attributes=sm.request
    )


async def test_cancel_before_initiated():
    sm, execution, result = make_sm()

    assert sm.request_cancel() is True

    assert sm.state is DecisionState.CANCELED_AFTER_REQUESTED
    assert execution.done() is True
    assert execution.cancelled() is True
    assert result.done() is True
    assert result.cancelled() is True
    assert sm.get_decision() == record_immediate_cancel(sm.request)


async def test_initiated_transitions_to_recorded():
    sm, execution, result = make_sm()

    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())

    assert sm.state is DecisionState.RECORDED
    assert execution.done() is False
    assert result.done() is False
    assert sm.get_decision() is None


async def test_cancel_after_recorded():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())

    assert sm.request_cancel() is True

    assert sm.state is DecisionState.CANCELED_AFTER_RECORDED
    assert execution.done() is True
    assert execution.cancelled() is True
    assert result.done() is False


async def test_cancel_after_started():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-1")
        )
    )

    assert sm.request_cancel() is True

    # Once the child has started we know the run_id, so use CANCELED_AFTER_STARTED
    # (not CANCELED_AFTER_RECORDED) so the cancel decision includes it.
    assert sm.state is DecisionState.CANCELED_AFTER_STARTED
    assert execution.done() is True
    assert result.done() is False


async def test_cancel_after_started_includes_run_id():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-42")
        )
    )
    sm.request_cancel()

    cancel_decision = sm.get_decision()
    assert cancel_decision is not None
    attrs = (
        cancel_decision.request_cancel_external_workflow_execution_decision_attributes
    )
    assert attrs.workflow_execution.run_id == "run-42"
    assert attrs.workflow_execution.workflow_id == WF_ID


async def test_cancel_returns_false_when_completed():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-1")
        )
    )
    sm.handle_completed(
        history.ChildWorkflowExecutionCompletedEventAttributes(
            result=Payload(data=b"done")
        )
    )

    assert sm.request_cancel() is False


async def test_handle_initiation_failed_reuses_same_exception():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())

    sm.handle_initiation_failed(
        history.StartChildWorkflowExecutionFailedEventAttributes(
            workflow_id=WF_ID,
        )
    )

    assert sm.state is DecisionState.COMPLETED
    assert execution.done() is True
    assert result.done() is True
    with pytest.raises(StartChildWorkflowExecutionFailed, match="start child failed"):
        execution.result()
    with pytest.raises(StartChildWorkflowExecutionFailed, match="start child failed"):
        result.result()

    # Both futures hold the identical exception object (not just equal ones).
    exc_execution = execution.exception()
    exc_result = result.exception()
    assert exc_execution is exc_result


async def test_handle_started_resolves_execution_future():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())

    wf_exec = WorkflowExecution(workflow_id=WF_ID, run_id="run-42")
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(workflow_execution=wf_exec)
    )

    assert sm.state is DecisionState.STARTED
    assert execution.done() is True
    assert execution.result() == wf_exec
    assert result.done() is False


async def test_handle_completed():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-1")
        )
    )

    payload = Payload(data=b"output")
    sm.handle_completed(
        history.ChildWorkflowExecutionCompletedEventAttributes(result=payload)
    )

    assert sm.state is DecisionState.COMPLETED
    assert result.done() is True
    assert result.result() == payload
    assert sm.get_decision() is None


async def test_handle_failed():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-1")
        )
    )

    sm.handle_failed(
        history.ChildWorkflowExecutionFailedEventAttributes(
            failure=Failure(reason="boom")
        )
    )

    assert sm.state is DecisionState.COMPLETED
    with pytest.raises(ChildWorkflowExecutionFailed, match="boom"):
        result.result()


async def test_handle_canceled():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-1")
        )
    )

    sm.handle_canceled(
        history.ChildWorkflowExecutionCanceledEventAttributes(
            details=Payload(data=b"cancel-details")
        )
    )

    assert sm.state is DecisionState.COMPLETED
    with pytest.raises(ChildWorkflowExecutionCanceled, match="child workflow canceled"):
        result.result()


async def test_handle_timed_out():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-1")
        )
    )

    sm.handle_timed_out(history.ChildWorkflowExecutionTimedOutEventAttributes())

    assert sm.state is DecisionState.COMPLETED
    with pytest.raises(
        ChildWorkflowExecutionTimedOut, match="child workflow timed out"
    ):
        result.result()


async def test_handle_terminated():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-1")
        )
    )

    sm.handle_terminated(history.ChildWorkflowExecutionTerminatedEventAttributes())

    assert sm.state is DecisionState.COMPLETED
    with pytest.raises(ChildWorkflowExecutionTerminated):
        result.result()


async def test_cancel_initiated_transitions_to_cancellation_recorded():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.request_cancel()

    sm.handle_cancel_initiated(
        history.RequestCancelExternalWorkflowExecutionInitiatedEventAttributes()
    )

    assert sm.state is DecisionState.CANCELLATION_RECORDED


async def test_cancel_failed_reverts_to_started():
    sm, execution, result = make_sm()
    sm.handle_initiated(history.StartChildWorkflowExecutionInitiatedEventAttributes())
    sm.handle_started(
        history.ChildWorkflowExecutionStartedEventAttributes(
            workflow_execution=WorkflowExecution(workflow_id=WF_ID, run_id="run-1")
        )
    )
    sm.request_cancel()
    sm.handle_cancel_initiated(
        history.RequestCancelExternalWorkflowExecutionInitiatedEventAttributes()
    )

    sm.handle_cancel_failed(
        history.RequestCancelExternalWorkflowExecutionFailedEventAttributes()
    )

    assert sm.state is DecisionState.STARTED
    assert result.done() is False
