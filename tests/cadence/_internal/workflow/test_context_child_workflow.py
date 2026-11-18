import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.protobuf.duration_pb2 import Duration

from cadence._internal.workflow.context import Context, _activate_workflow_context
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence.api.v1 import history, workflow_pb2
from cadence.api.v1.common_pb2 import Failure, WorkflowExecution, WorkflowType
from cadence.api.v1.decision_pb2 import StartChildWorkflowExecutionDecisionAttributes
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.data_converter import DefaultDataConverter
from cadence.error import (
    ChildWorkflowExecutionFailed,
    StartChildWorkflowExecutionFailed,
)
from cadence import workflow
from cadence.workflow import ChildWorkflowFuture, WorkflowInfo


def _make_ctx(run_id: str = "rid") -> tuple[Context, MagicMock]:
    dm = MagicMock(wraps=DecisionManager(asyncio.get_running_loop()))
    info = WorkflowInfo(
        workflow_type="ParentWf",
        workflow_domain="domain",
        workflow_id="wid",
        workflow_run_id=run_id,
        workflow_task_list="tl",
        data_converter=DefaultDataConverter(),
    )
    ctx = Context(info, dm)
    return ctx, dm


def _start_child_workflow(
    ctx: Context, *args: Any, **kwargs: Any
) -> asyncio.Future[ChildWorkflowFuture[Any]]:
    with _activate_workflow_context(ctx):
        # The task copies the active context when it is created.
        return asyncio.ensure_future(workflow.start_child_workflow(*args, **kwargs))


def _start_child(dm: MagicMock, workflow_id: str, run_id: str = "run-1") -> None:
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=1,
            start_child_workflow_execution_initiated_event_attributes=history.StartChildWorkflowExecutionInitiatedEventAttributes(
                workflow_id=workflow_id,
            ),
        )
    )
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=2,
            child_workflow_execution_started_event_attributes=history.ChildWorkflowExecutionStartedEventAttributes(
                initiated_event_id=1,
                workflow_execution=WorkflowExecution(
                    workflow_id=workflow_id, run_id=run_id
                ),
            ),
        )
    )


def _complete_child(dm: MagicMock, result: object) -> None:
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=3,
            child_workflow_execution_completed_event_attributes=history.ChildWorkflowExecutionCompletedEventAttributes(
                initiated_event_id=1,
                result=DefaultDataConverter().to_data([result]),
            ),
        )
    )


def _fail_child(dm: MagicMock, reason: str) -> None:
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=3,
            child_workflow_execution_failed_event_attributes=history.ChildWorkflowExecutionFailedEventAttributes(
                initiated_event_id=1,
                failure=Failure(reason=reason),
            ),
        )
    )


@pytest.mark.asyncio
async def test_execute_child_workflow_basic():
    ctx, dm = _make_ctx()

    future = ctx.execute_child_workflow(
        "ChildWf",
        str,
        "arg1",
        "arg2",
        execution_start_to_close_timeout=timedelta(minutes=10),
    )
    _start_child(dm, future.workflow_id)
    _complete_child(dm, "result")
    result = await future

    dm.schedule_child_workflow.assert_called_once()
    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert attrs.workflow_type == WorkflowType(name="ChildWf")
    assert attrs.domain == "domain"
    assert attrs.task_list == TaskList(
        kind=TaskListKind.TASK_LIST_KIND_NORMAL, name="tl"
    )
    assert attrs.execution_start_to_close_timeout == Duration(seconds=600)
    assert attrs.task_start_to_close_timeout == Duration(seconds=10)
    assert result == "result"


@pytest.mark.asyncio
async def test_execute_child_workflow_with_memo():
    ctx, dm = _make_ctx()
    dc = ctx.data_converter()

    ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=10),
        memo={"k1": "v1", "k2": 99},
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert len(attrs.memo.fields) == 2
    assert attrs.memo.fields["k1"] == dc.to_data(["v1"])
    assert attrs.memo.fields["k2"] == dc.to_data([99])


@pytest.mark.asyncio
async def test_execute_child_workflow_auto_generates_workflow_id():
    ctx, dm = _make_ctx(run_id="test-run-id")

    ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=5),
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert attrs.workflow_id == "test-run-id_0"
    assert dm.schedule_child_workflow.call_args.kwargs["parent_workflow_run_id"] == (
        "test-run-id"
    )


@pytest.mark.asyncio
async def test_execute_child_workflow_uses_provided_workflow_id():
    ctx, dm = _make_ctx()

    ctx.execute_child_workflow(
        "ChildWf",
        str,
        workflow_id="my-child-1",
        execution_start_to_close_timeout=timedelta(minutes=5),
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert attrs.workflow_id == "my-child-1"


@pytest.mark.asyncio
async def test_execute_child_workflow_raises_without_execution_timeout():
    ctx, dm = _make_ctx()

    with pytest.raises(
        ValueError, match="execution_start_to_close_timeout is required"
    ):
        ctx.execute_child_workflow("ChildWf", str)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [timedelta(0), timedelta(seconds=-1)])
async def test_execute_child_workflow_raises_for_invalid_execution_timeout(
    timeout: timedelta,
):
    ctx, dm = _make_ctx()

    with pytest.raises(
        ValueError, match="execution_start_to_close_timeout must be greater than 0"
    ):
        ctx.execute_child_workflow(
            "ChildWf",
            str,
            execution_start_to_close_timeout=timeout,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [timedelta(0), timedelta(seconds=-1)])
async def test_execute_child_workflow_raises_for_invalid_task_timeout(
    timeout: timedelta,
):
    ctx, dm = _make_ctx()

    with pytest.raises(
        ValueError, match="task_start_to_close_timeout must be greater than 0"
    ):
        ctx.execute_child_workflow(
            "ChildWf",
            str,
            execution_start_to_close_timeout=timedelta(minutes=5),
            task_start_to_close_timeout=timeout,
        )


@pytest.mark.asyncio
async def test_execute_child_workflow_raises_for_invalid_workflow_id_reuse_policy():
    ctx, dm = _make_ctx()

    with pytest.raises(
        ValueError,
        match="workflow_id_reuse_policy cannot be WORKFLOW_ID_REUSE_POLICY_INVALID",
    ):
        ctx.execute_child_workflow(
            "ChildWf",
            str,
            execution_start_to_close_timeout=timedelta(minutes=5),
            workflow_id_reuse_policy=workflow_pb2.WORKFLOW_ID_REUSE_POLICY_INVALID,
        )


@pytest.mark.asyncio
async def test_execute_child_workflow_default_values():
    ctx, dm = _make_ctx()

    ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=5),
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert attrs.task_start_to_close_timeout == Duration(seconds=10)
    assert attrs.parent_close_policy == workflow_pb2.PARENT_CLOSE_POLICY_TERMINATE
    assert (
        attrs.workflow_id_reuse_policy
        == workflow_pb2.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE_FAILED_ONLY
    )


@pytest.mark.asyncio
async def test_execute_child_workflow_custom_options():
    ctx, dm = _make_ctx()

    ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=5),
        parent_close_policy=workflow_pb2.PARENT_CLOSE_POLICY_ABANDON,
        domain="other-domain",
        task_list="other-tl",
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert attrs.parent_close_policy == workflow_pb2.PARENT_CLOSE_POLICY_ABANDON
    assert attrs.domain == "other-domain"
    assert attrs.task_list == TaskList(
        kind=TaskListKind.TASK_LIST_KIND_NORMAL, name="other-tl"
    )


@pytest.mark.asyncio
async def test_execute_child_workflow_retry_policy():
    ctx, dm = _make_ctx()

    ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=5),
        retry_policy={
            "initial_interval": timedelta(seconds=2),
            "backoff_coefficient": 2.0,
            "maximum_attempts": 3,
        },
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    rp = attrs.retry_policy
    assert rp is not None
    assert rp.initial_interval == Duration(seconds=2)
    assert rp.backoff_coefficient == 2.0
    assert rp.maximum_attempts == 3


@pytest.mark.asyncio
async def test_execute_child_workflow_deserializes_result():
    ctx, dm = _make_ctx()

    future = ctx.execute_child_workflow(
        "ChildWf",
        int,
        execution_start_to_close_timeout=timedelta(minutes=5),
    )
    _start_child(dm, future.workflow_id)
    _complete_child(dm, 42)

    result = await future
    assert result == 42
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_execute_child_workflow_propagates_errors():
    ctx, dm = _make_ctx()

    future = ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=5),
    )
    _start_child(dm, future.workflow_id)
    _fail_child(dm, "child failed")

    with pytest.raises(ChildWorkflowExecutionFailed, match="child failed"):
        await future


@pytest.mark.asyncio
async def test_execute_child_workflow_cron_schedule():
    ctx, dm = _make_ctx()

    ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=5),
        cron_schedule="* * * * *",
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert attrs.cron_schedule == "* * * * *"


@pytest.mark.asyncio
async def test_start_child_workflow_waits_for_child_to_start():
    ctx, dm = _make_ctx()

    start = _start_child_workflow(
        ctx,
        "ChildWf",
        str,
        workflow_id="child-1",
        execution_start_to_close_timeout=timedelta(minutes=5),
    )
    await asyncio.sleep(0)
    assert start.done() is False

    _start_child(dm, "child-1", run_id="run-1")
    future = await start

    assert future.workflow_id == "child-1"
    assert future.run_id == "run-1"


@pytest.mark.asyncio
async def test_start_child_workflow_future_awaitable():
    ctx, dm = _make_ctx()

    start = _start_child_workflow(
        ctx,
        "ChildWf",
        int,
        workflow_id="child-1",
        execution_start_to_close_timeout=timedelta(minutes=5),
    )
    await asyncio.sleep(0)
    _start_child(dm, "child-1")
    future = await start
    _complete_child(dm, 42)

    result = await future
    assert result == 42
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_child_workflow_future_cancel_requests_cancellation():
    ctx, dm = _make_ctx()

    future = ctx.execute_child_workflow(
        "ChildWf",
        str,
        workflow_id="child-1",
        execution_start_to_close_timeout=timedelta(minutes=5),
    )
    _start_child(dm, "child-1", run_id="run-1")

    future.cancel()

    decisions = dm.collect_pending_decisions()
    assert len(decisions) == 1
    cancel = decisions[0].request_cancel_external_workflow_execution_decision_attributes
    assert cancel.workflow_execution == WorkflowExecution(
        workflow_id="child-1", run_id="run-1"
    )
    assert cancel.child_workflow_only is True


@pytest.mark.asyncio
async def test_start_child_workflow_raises_when_start_fails():
    ctx, dm = _make_ctx()

    start = _start_child_workflow(
        ctx,
        "ChildWf",
        str,
        workflow_id="child-1",
        execution_start_to_close_timeout=timedelta(minutes=5),
    )
    await asyncio.sleep(0)
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=1,
            start_child_workflow_execution_initiated_event_attributes=history.StartChildWorkflowExecutionInitiatedEventAttributes(
                workflow_id="child-1",
            ),
        )
    )
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=2,
            start_child_workflow_execution_failed_event_attributes=history.StartChildWorkflowExecutionFailedEventAttributes(
                initiated_event_id=1,
                workflow_id="child-1",
            ),
        )
    )

    with pytest.raises(StartChildWorkflowExecutionFailed):
        await start
