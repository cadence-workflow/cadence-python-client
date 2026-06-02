import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cadence._internal.workflow.context import Context
from cadence.api.v1.decision_pb2 import (
    SignalExternalWorkflowExecutionDecisionAttributes,
)
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo


def _make_ctx() -> tuple[Context, MagicMock]:
    dm = MagicMock()
    dc = DefaultDataConverter()
    info = WorkflowInfo(
        workflow_type="ParentWf",
        workflow_domain="domain",
        workflow_id="wid",
        workflow_run_id="rid",
        workflow_task_list="tl",
        data_converter=dc,
    )
    ctx = Context(info, dm)
    return ctx, dm


def _setup_signal_mock(
    dm: MagicMock,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    loop = loop or asyncio.get_event_loop()
    future: asyncio.Future[None] = loop.create_future()
    future.set_result(None)
    dm.signal_external_workflow = MagicMock(return_value=future)


def _attrs(dm: MagicMock) -> SignalExternalWorkflowExecutionDecisionAttributes:
    return dm.signal_external_workflow.call_args[0][0]


# ---------------------------------------------------------------------------
# signal_child_workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signal_child_workflow_basic():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    await ctx.signal_child_workflow("child-wf-1", "my_signal", "arg1")

    dm.signal_external_workflow.assert_called_once()
    attrs = _attrs(dm)
    assert attrs.signal_name == "my_signal"
    assert attrs.workflow_execution.workflow_id == "child-wf-1"
    assert attrs.domain == "domain"


@pytest.mark.asyncio
async def test_signal_child_workflow_serializes_args():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)
    dc = DefaultDataConverter()

    await ctx.signal_child_workflow("child-wf-1", "my_signal", "hello", 42)

    deserialized = dc.from_data(_attrs(dm).input, [str, int])
    assert deserialized == ["hello", 42]


@pytest.mark.asyncio
async def test_signal_child_workflow_sets_child_workflow_only():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    await ctx.signal_child_workflow("child-wf-1", "my_signal")

    assert _attrs(dm).child_workflow_only is True


@pytest.mark.asyncio
async def test_signal_child_workflow_uses_empty_run_id():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    await ctx.signal_child_workflow("child-wf-1", "my_signal")

    assert _attrs(dm).workflow_execution.run_id == ""


@pytest.mark.asyncio
async def test_signal_child_workflow_rejects_empty_id():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    with pytest.raises(ValueError, match="child_workflow_id must not be empty"):
        await ctx.signal_child_workflow("", "my_signal")

    dm.signal_external_workflow.assert_not_called()


# ---------------------------------------------------------------------------
# signal_external_workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signal_external_workflow_basic():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    await ctx.signal_external_workflow("ext-wf-1", "ping")

    dm.signal_external_workflow.assert_called_once()
    attrs = _attrs(dm)
    assert attrs.signal_name == "ping"
    assert attrs.workflow_execution.workflow_id == "ext-wf-1"
    assert attrs.child_workflow_only is False


@pytest.mark.asyncio
async def test_signal_external_workflow_defaults_to_own_domain():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    await ctx.signal_external_workflow("ext-wf-1", "ping")

    assert _attrs(dm).domain == "domain"


@pytest.mark.asyncio
async def test_signal_external_workflow_custom_domain():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    await ctx.signal_external_workflow("ext-wf-1", "ping", domain="other-domain")

    assert _attrs(dm).domain == "other-domain"


@pytest.mark.asyncio
async def test_signal_external_workflow_forwards_run_id():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    await ctx.signal_external_workflow("ext-wf-1", "ping", run_id="run-42")

    assert _attrs(dm).workflow_execution.run_id == "run-42"


@pytest.mark.asyncio
async def test_signal_external_workflow_default_run_id_is_empty():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    await ctx.signal_external_workflow("ext-wf-1", "ping")

    assert _attrs(dm).workflow_execution.run_id == ""


@pytest.mark.asyncio
async def test_signal_external_workflow_serializes_args():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)
    dc = DefaultDataConverter()

    await ctx.signal_external_workflow("ext-wf-1", "ping", "hello", 99)

    deserialized = dc.from_data(_attrs(dm).input, [str, int])
    assert deserialized == ["hello", 99]


@pytest.mark.asyncio
async def test_signal_external_workflow_rejects_empty_id():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    with pytest.raises(ValueError, match="workflow_id must not be empty"):
        await ctx.signal_external_workflow("", "ping")

    dm.signal_external_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_signal_external_workflow_rejects_empty_signal_name():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    with pytest.raises(ValueError, match="signal_name must not be empty"):
        await ctx.signal_external_workflow("wf-1", "")

    dm.signal_external_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_signal_child_workflow_rejects_empty_signal_name():
    ctx, dm = _make_ctx()
    _setup_signal_mock(dm)

    with pytest.raises(ValueError, match="signal_name must not be empty"):
        await ctx.signal_child_workflow("child-wf-1", "")

    dm.signal_external_workflow.assert_not_called()


# ---------------------------------------------------------------------------
# ChildWorkflowFuture.signal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_child_workflow_future_signal_delegates_to_context():
    from cadence.workflow import ChildWorkflowFuture

    dc = DefaultDataConverter()
    loop = asyncio.get_event_loop()
    result_future: asyncio.Future = loop.create_future()

    future = ChildWorkflowFuture(
        workflow_id="child-wf-1",
        run_id="",
        result_future=result_future,
        result_type=str,
        data_converter=dc,
    )

    mock_ctx = AsyncMock()
    with patch("cadence.workflow.WorkflowContext.get", return_value=mock_ctx):
        await future.signal("hello_signal", "arg1", "arg2")

    mock_ctx.signal_child_workflow.assert_awaited_once_with(
        "child-wf-1", "hello_signal", "arg1", "arg2"
    )


# ---------------------------------------------------------------------------
# Public cadence.workflow.signal_external_workflow wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_signal_external_workflow_delegates():
    import cadence.workflow as wf

    mock_ctx = AsyncMock()
    with patch("cadence.workflow.WorkflowContext.get", return_value=mock_ctx):
        await wf.signal_external_workflow(
            "wf-id", "my_signal", "a", run_id="r1", domain="d1"
        )

    mock_ctx.signal_external_workflow.assert_awaited_once_with(
        "wf-id", "my_signal", "a", run_id="r1", domain="d1"
    )
