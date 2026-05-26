import asyncio
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from google.protobuf.duration_pb2 import Duration

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.statemachine.child_workflow_execution_state_machine import (
    ChildWorkflowExecutionFailed,
)
from cadence.api.v1 import workflow_pb2
from cadence.api.v1.common_pb2 import WorkflowType
from cadence.api.v1.decision_pb2 import StartChildWorkflowExecutionDecisionAttributes
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo


def _make_ctx(run_id: str = "rid") -> tuple[Context, MagicMock]:
    dm = MagicMock()
    dc = DefaultDataConverter()
    info = WorkflowInfo(
        workflow_type="ParentWf",
        workflow_domain="domain",
        workflow_id="wid",
        workflow_run_id=run_id,
        workflow_task_list="tl",
        data_converter=dc,
    )
    ctx = Context(info, dm)
    return ctx, dm


def _setup_schedule_mock(
    dm: MagicMock,
    result_value: object = "result",
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    dc = DefaultDataConverter()
    loop = loop or asyncio.get_event_loop()
    execution_future: asyncio.Future = loop.create_future()
    execution_future.set_result(None)
    result_future: asyncio.Future = loop.create_future()
    result_future.set_result(dc.to_data([result_value]))
    dm.schedule_child_workflow = MagicMock(
        return_value=(execution_future, result_future)
    )


def _setup_schedule_mock_error(
    dm: MagicMock, error: Exception, loop: asyncio.AbstractEventLoop | None = None
) -> None:
    loop = loop or asyncio.get_event_loop()
    execution_future: asyncio.Future = loop.create_future()
    execution_future.set_result(None)
    result_future: asyncio.Future = loop.create_future()
    result_future.set_exception(error)
    dm.schedule_child_workflow = MagicMock(
        return_value=(execution_future, result_future)
    )


@pytest.mark.asyncio
async def test_execute_child_workflow_basic():
    ctx, dm = _make_ctx()
    _setup_schedule_mock(dm)

    result = await ctx.execute_child_workflow(
        "ChildWf",
        str,
        "arg1",
        "arg2",
        execution_start_to_close_timeout=timedelta(minutes=10),
    )

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
async def test_execute_child_workflow_auto_generates_workflow_id():
    ctx, dm = _make_ctx(run_id="test-run-id")
    _setup_schedule_mock(dm)

    await ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=5),
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert attrs.workflow_id == ""
    assert dm.schedule_child_workflow.call_args.kwargs["parent_workflow_run_id"] == (
        "test-run-id"
    )


@pytest.mark.asyncio
async def test_execute_child_workflow_uses_provided_workflow_id():
    ctx, dm = _make_ctx()
    _setup_schedule_mock(dm)

    await ctx.execute_child_workflow(
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
        await ctx.execute_child_workflow("ChildWf", str)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [timedelta(0), timedelta(seconds=-1)])
async def test_execute_child_workflow_raises_for_invalid_execution_timeout(
    timeout: timedelta,
):
    ctx, dm = _make_ctx()

    with pytest.raises(
        ValueError, match="execution_start_to_close_timeout must be greater than 0"
    ):
        await ctx.execute_child_workflow(
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
        await ctx.execute_child_workflow(
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
        await ctx.execute_child_workflow(
            "ChildWf",
            str,
            execution_start_to_close_timeout=timedelta(minutes=5),
            workflow_id_reuse_policy=workflow_pb2.WORKFLOW_ID_REUSE_POLICY_INVALID,
        )


@pytest.mark.asyncio
async def test_execute_child_workflow_default_values():
    ctx, dm = _make_ctx()
    _setup_schedule_mock(dm)

    await ctx.execute_child_workflow(
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
    _setup_schedule_mock(dm)

    await ctx.execute_child_workflow(
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
    _setup_schedule_mock(dm)

    await ctx.execute_child_workflow(
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
    _setup_schedule_mock(dm, result_value=42)

    result = await ctx.execute_child_workflow(
        "ChildWf",
        int,
        execution_start_to_close_timeout=timedelta(minutes=5),
    )

    assert result == 42
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_execute_child_workflow_propagates_errors():
    ctx, dm = _make_ctx()
    failure = ChildWorkflowExecutionFailed("child failed", failure=None)
    _setup_schedule_mock_error(dm, failure)

    with pytest.raises(ChildWorkflowExecutionFailed, match="child failed"):
        await ctx.execute_child_workflow(
            "ChildWf",
            str,
            execution_start_to_close_timeout=timedelta(minutes=5),
        )


@pytest.mark.asyncio
async def test_execute_child_workflow_cron_schedule():
    ctx, dm = _make_ctx()
    _setup_schedule_mock(dm)

    await ctx.execute_child_workflow(
        "ChildWf",
        str,
        execution_start_to_close_timeout=timedelta(minutes=5),
        cron_schedule="* * * * *",
    )

    attrs: StartChildWorkflowExecutionDecisionAttributes = (
        dm.schedule_child_workflow.call_args[0][0]
    )
    assert attrs.cron_schedule == "* * * * *"
