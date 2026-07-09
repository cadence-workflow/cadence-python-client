"""Tests for activity execution and response metrics in ActivityExecutor."""

import time
from typing import cast
import pytest
from unittest.mock import AsyncMock, Mock, PropertyMock

from google.protobuf.timestamp_pb2 import Timestamp

from cadence._internal.activity import ActivityExecutor
from cadence.api.v1.common_pb2 import ActivityType, WorkflowType, WorkflowExecution
from cadence.api.v1.service_worker_pb2 import (
    PollForActivityTaskResponse,
    RespondActivityTaskCompletedResponse,
    RespondActivityTaskFailedResponse,
)
from cadence.client import Client
from cadence.data_converter import DefaultDataConverter
from cadence.metrics import MetricsEmitter
from cadence.metrics.constants import (
    ACTIVITY_END_TO_END_LATENCY,
    ACTIVITY_EXECUTION_FAILED_COUNTER,
    ACTIVITY_EXECUTION_LATENCY,
    ACTIVITY_RESPONSE_FAILED_COUNTER,
    ACTIVITY_RESPONSE_LATENCY,
    ACTIVITY_TASK_COMPLETED_COUNTER,
    ACTIVITY_TASK_FAILED_COUNTER,
    TAG_ACTIVITY_TYPE,
    TAG_DOMAIN,
    TAG_TASK_LIST,
    TAG_WORKFLOW_TYPE,
)
from cadence.worker._registry import Registry

DOMAIN = "test-domain"
TASK_LIST = "test-tl"
ACTIVITY_TYPE = "my_activity"
WF_TYPE = "MyWorkflow"
EXPECTED_TAGS = {
    TAG_ACTIVITY_TYPE: ACTIVITY_TYPE,
    TAG_WORKFLOW_TYPE: WF_TYPE,
    TAG_DOMAIN: DOMAIN,
    TAG_TASK_LIST: TASK_LIST,
}


def _mock_emitter() -> Mock:
    emitter = Mock(spec=MetricsEmitter)
    # with_tags returns a child emitter that all per-task metrics route through.
    emitter.with_tags.return_value = Mock(spec=MetricsEmitter)
    return emitter


def _tagged(emitter: Mock) -> Mock:
    return cast(Mock, emitter.with_tags.return_value)


def _make_ts(seconds: int) -> Timestamp:
    ts = Timestamp()
    ts.seconds = seconds
    return ts


def _mock_client() -> Mock:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value=DOMAIN)
    client.data_converter = DefaultDataConverter()
    stub = AsyncMock()
    stub.RespondActivityTaskCompleted = AsyncMock(
        return_value=RespondActivityTaskCompletedResponse()
    )
    stub.RespondActivityTaskFailed = AsyncMock(
        return_value=RespondActivityTaskFailedResponse()
    )
    client.worker_stub = stub
    return client


def _make_task(scheduled_secs: int = 1) -> PollForActivityTaskResponse:
    task = PollForActivityTaskResponse(
        task_token=b"token",
        activity_id="act-1",
        activity_type=ActivityType(name=ACTIVITY_TYPE),
        workflow_type=WorkflowType(name=WF_TYPE),
        workflow_domain=DOMAIN,
        workflow_execution=WorkflowExecution(workflow_id="wf-1", run_id="run-1"),
    )
    task.scheduled_time.seconds = scheduled_secs
    task.started_time.seconds = scheduled_secs
    return task


def _make_executor(emitter=None, registry=None) -> ActivityExecutor:
    client = _mock_client()
    if registry is None:
        registry = Registry()
    return ActivityExecutor(
        client, TASK_LIST, "test-id", 1, registry.get_activity, emitter
    )


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


class TestActivityExecutionSuccess:
    @pytest.mark.asyncio
    async def test_emits_execution_latency_and_completed_counter(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            return "ok"

        executor = _make_executor(emitter, reg)
        await executor.execute(_make_task())

        histogram_names = [c.args[0] for c in _tagged(emitter).histogram.call_args_list]
        counter_names = [c.args[0] for c in _tagged(emitter).counter.call_args_list]
        assert ACTIVITY_EXECUTION_LATENCY in histogram_names
        assert ACTIVITY_RESPONSE_LATENCY in histogram_names
        assert ACTIVITY_TASK_COMPLETED_COUNTER in counter_names

    @pytest.mark.asyncio
    async def test_emits_end_to_end_latency_when_scheduled_time_set(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            return "ok"

        executor = _make_executor(emitter, reg)
        scheduled = int(time.time()) - 5
        await executor.execute(_make_task(scheduled_secs=scheduled))

        histogram_names = [c.args[0] for c in _tagged(emitter).histogram.call_args_list]
        assert ACTIVITY_END_TO_END_LATENCY in histogram_names
        e2e_call = next(
            c
            for c in _tagged(emitter).histogram.call_args_list
            if c.args[0] == ACTIVITY_END_TO_END_LATENCY
        )
        assert 1e9 < e2e_call.args[1] < 30e9

    @pytest.mark.asyncio
    async def test_skips_end_to_end_latency_when_scheduled_time_is_missing(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            return "ok"

        executor = _make_executor(emitter, reg)
        await executor.execute(_make_task(scheduled_secs=0))

        histogram_names = [c.args[0] for c in _tagged(emitter).histogram.call_args_list]
        assert ACTIVITY_END_TO_END_LATENCY not in histogram_names

    @pytest.mark.asyncio
    async def test_skips_end_to_end_latency_when_scheduled_time_is_in_the_future(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            return "ok"

        executor = _make_executor(emitter, reg)
        await executor.execute(_make_task(scheduled_secs=int(time.time()) + 60))

        histogram_names = [c.args[0] for c in _tagged(emitter).histogram.call_args_list]
        assert ACTIVITY_END_TO_END_LATENCY not in histogram_names

    @pytest.mark.asyncio
    async def test_emits_response_failed_counter_when_respond_rpc_fails(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            return "ok"

        executor = _make_executor(emitter, reg)
        executor._client.worker_stub.RespondActivityTaskCompleted = AsyncMock(
            side_effect=RuntimeError("rpc failed")
        )

        await executor.execute(_make_task())  # should not raise

        counter_names = [c.args[0] for c in _tagged(emitter).counter.call_args_list]
        assert ACTIVITY_RESPONSE_FAILED_COUNTER in counter_names


# ---------------------------------------------------------------------------
# Failed execution
# ---------------------------------------------------------------------------


class TestActivityExecutionFailure:
    @pytest.mark.asyncio
    async def test_emits_execution_latency_and_failed_counter(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            raise ValueError("activity error")

        executor = _make_executor(emitter, reg)
        await executor.execute(_make_task())

        histogram_names = [c.args[0] for c in _tagged(emitter).histogram.call_args_list]
        counter_names = [c.args[0] for c in _tagged(emitter).counter.call_args_list]
        assert ACTIVITY_EXECUTION_LATENCY in histogram_names
        assert ACTIVITY_EXECUTION_FAILED_COUNTER in counter_names

    @pytest.mark.asyncio
    async def test_emits_task_failed_counter_after_respond(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            raise ValueError("activity error")

        executor = _make_executor(emitter, reg)
        await executor.execute(_make_task())

        counter_names = [c.args[0] for c in _tagged(emitter).counter.call_args_list]
        assert ACTIVITY_TASK_FAILED_COUNTER in counter_names

    @pytest.mark.asyncio
    async def test_emits_response_latency_on_failure(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            raise ValueError("oops")

        executor = _make_executor(emitter, reg)
        await executor.execute(_make_task())

        histogram_names = [c.args[0] for c in _tagged(emitter).histogram.call_args_list]
        assert ACTIVITY_RESPONSE_LATENCY in histogram_names

    @pytest.mark.asyncio
    async def test_tags_include_activity_and_workflow_type(self):
        emitter = _mock_emitter()
        reg = Registry()

        @reg.activity(name=ACTIVITY_TYPE)
        async def my_activity():
            return "done"

        executor = _make_executor(emitter, reg)
        await executor.execute(_make_task())

        emitter.with_tags.assert_called_once_with(EXPECTED_TAGS)
