"""Tests for poll and worker-start metrics in DecisionWorker and ActivityWorker."""

import pytest
from unittest.mock import AsyncMock, Mock, PropertyMock, patch
from google.protobuf.timestamp_pb2 import Timestamp

from cadence.client import Client
from cadence.error import CadenceRpcError
from cadence.metrics import MetricsEmitter, NoOpMetricsEmitter
from cadence.metrics.metrics import _TaggedEmitter
from cadence.metrics.constants import (
    ACTIVITY_POLL_COUNTER,
    ACTIVITY_POLL_FAILED_COUNTER,
    ACTIVITY_POLL_LATENCY,
    ACTIVITY_POLL_NO_TASK_COUNTER,
    ACTIVITY_POLL_SUCCEED_COUNTER,
    ACTIVITY_POLL_TRANSIENT_FAILED_COUNTER,
    ACTIVITY_SCHEDULED_TO_START_LATENCY,
    DECISION_POLL_COUNTER,
    DECISION_POLL_FAILED_COUNTER,
    DECISION_POLL_LATENCY,
    DECISION_POLL_NO_TASK_COUNTER,
    DECISION_POLL_SUCCEED_COUNTER,
    DECISION_POLL_TRANSIENT_FAILED_COUNTER,
    DECISION_SCHEDULED_TO_START_LATENCY,
    POLLER_START_COUNTER,
    TAG_DOMAIN,
    TAG_TASK_LIST,
    WORKER_PANIC_COUNTER,
    WORKER_START_COUNTER,
)
from cadence.worker._activity import ActivityWorker
from cadence.worker._decision import DecisionWorker
from cadence.worker._registry import Registry
from cadence.worker._types import WorkerOptions
from grpc import StatusCode

DOMAIN = "test-domain"
TASK_LIST = "test-tl"
EXPECTED_TAGS = {TAG_DOMAIN: DOMAIN, TAG_TASK_LIST: TASK_LIST}


def _mock_emitter() -> Mock:
    emitter = Mock(spec=MetricsEmitter)
    emitter.with_tags.side_effect = lambda tags: _TaggedEmitter(emitter, tags)
    return emitter


def _mock_client() -> Mock:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value=DOMAIN)
    type(client).identity = PropertyMock(return_value="test-identity")
    client.metrics_emitter = NoOpMetricsEmitter()
    stub = Mock()
    stub.PollForDecisionTask = AsyncMock(return_value=Mock(task_token=b""))
    stub.PollForActivityTask = AsyncMock(return_value=Mock(task_token=b""))
    client.worker_stub = stub
    return client


def _worker_options(emitter) -> WorkerOptions:
    return {
        "identity": "test-id",
        "metrics_emitter": emitter,
        "max_concurrent_decision_task_execution_size": 1,
        "decision_task_pollers": 1,
        "max_concurrent_activity_execution_size": 1,
        "activity_task_pollers": 1,
        "disable_workflow_worker": False,
        "disable_activity_worker": False,
    }


def _make_ts(seconds: int, nanos: int = 0) -> Timestamp:
    ts = Timestamp()
    ts.seconds = seconds
    ts.nanos = nanos
    return ts


# ---------------------------------------------------------------------------
# DecisionWorker: run() metrics
# ---------------------------------------------------------------------------


class TestDecisionWorkerRunMetrics:
    @pytest.mark.asyncio
    async def test_emits_worker_start_counter(self):
        emitter = _mock_emitter()
        worker = DecisionWorker(
            _mock_client(), TASK_LIST, Registry(), _worker_options(emitter)
        )
        with patch.object(worker._poller, "run", new=AsyncMock()):
            await worker.run()

        emitter.counter.assert_any_call(WORKER_START_COUNTER, 1, tags=EXPECTED_TAGS)
        assert not any(
            call.args[0] == POLLER_START_COUNTER
            for call in emitter.counter.call_args_list
        )

    @pytest.mark.asyncio
    async def test_emits_poller_start_counter_with_configured_count(self):
        emitter = _mock_emitter()
        options = _worker_options(emitter)
        options["decision_task_pollers"] = 3
        worker = DecisionWorker(_mock_client(), TASK_LIST, Registry(), options)
        with patch.object(worker._poller, "_poll_loop", new_callable=AsyncMock):
            await worker.run()

        emitter.counter.assert_any_call(POLLER_START_COUNTER, 3, tags=EXPECTED_TAGS)

    @pytest.mark.asyncio
    async def test_emits_worker_panic_counter_on_exception(self):
        emitter = _mock_emitter()
        worker = DecisionWorker(
            _mock_client(), TASK_LIST, Registry(), _worker_options(emitter)
        )
        with patch.object(
            worker._poller,
            "run",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            with pytest.raises(RuntimeError):
                await worker.run()

        emitter.counter.assert_any_call(WORKER_PANIC_COUNTER, 1, tags=EXPECTED_TAGS)

    @pytest.mark.asyncio
    async def test_no_panic_counter_on_normal_exit(self):
        emitter = _mock_emitter()
        worker = DecisionWorker(
            _mock_client(), TASK_LIST, Registry(), _worker_options(emitter)
        )
        with patch.object(worker._poller, "run", new=AsyncMock()):
            await worker.run()

        calls = [str(c) for c in emitter.counter.call_args_list]
        assert not any(WORKER_PANIC_COUNTER in c for c in calls)


# ---------------------------------------------------------------------------
# DecisionWorker: _poll() metrics
# ---------------------------------------------------------------------------


class TestDecisionWorkerPollMetrics:
    @pytest.mark.asyncio
    async def test_emits_poll_counter_and_latency_on_empty_response(self):
        emitter = _mock_emitter()
        client = _mock_client()
        client.worker_stub.PollForDecisionTask = AsyncMock(
            return_value=Mock(task_token=b"")
        )
        worker = DecisionWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        result = await worker._poll()

        assert result is None
        emitter.counter.assert_any_call(DECISION_POLL_COUNTER, 1, tags=EXPECTED_TAGS)
        emitter.counter.assert_any_call(
            DECISION_POLL_NO_TASK_COUNTER, 1, tags=EXPECTED_TAGS
        )
        assert any(
            c.args[0] == DECISION_POLL_LATENCY for c in emitter.histogram.call_args_list
        )

    @pytest.mark.asyncio
    async def test_emits_succeed_counter_on_task(self):
        emitter = _mock_emitter()
        client = _mock_client()
        mock_task = Mock()
        mock_task.task_token = b"token"
        mock_task.scheduled_time = _make_ts(0)
        mock_task.started_time = _make_ts(0)
        client.worker_stub.PollForDecisionTask = AsyncMock(return_value=mock_task)
        worker = DecisionWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        result = await worker._poll()

        assert result is mock_task
        emitter.counter.assert_any_call(DECISION_POLL_COUNTER, 1, tags=EXPECTED_TAGS)
        emitter.counter.assert_any_call(
            DECISION_POLL_SUCCEED_COUNTER, 1, tags=EXPECTED_TAGS
        )

    @pytest.mark.asyncio
    async def test_emits_scheduled_to_start_latency_when_timestamps_set(self):
        emitter = _mock_emitter()
        client = _mock_client()
        mock_task = Mock()
        mock_task.task_token = b"token"
        mock_task.scheduled_time = _make_ts(1000)
        mock_task.started_time = _make_ts(1002)
        client.worker_stub.PollForDecisionTask = AsyncMock(return_value=mock_task)
        worker = DecisionWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        await worker._poll()

        histogram_calls = {c.args[0]: c for c in emitter.histogram.call_args_list}
        assert DECISION_SCHEDULED_TO_START_LATENCY in histogram_calls
        latency_call = histogram_calls[DECISION_SCHEDULED_TO_START_LATENCY]
        assert abs(latency_call.args[1] - 2.0) < 0.01

    @pytest.mark.asyncio
    async def test_no_scheduled_to_start_when_timestamps_zero(self):
        emitter = _mock_emitter()
        client = _mock_client()
        mock_task = Mock()
        mock_task.task_token = b"token"
        mock_task.scheduled_time = _make_ts(0)
        mock_task.started_time = _make_ts(0)
        client.worker_stub.PollForDecisionTask = AsyncMock(return_value=mock_task)
        worker = DecisionWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        await worker._poll()

        histogram_names = [c.args[0] for c in emitter.histogram.call_args_list]
        assert DECISION_SCHEDULED_TO_START_LATENCY not in histogram_names

    @pytest.mark.asyncio
    async def test_clamps_negative_scheduled_to_start_latency(self):
        emitter = _mock_emitter()
        client = _mock_client()
        mock_task = Mock()
        mock_task.task_token = b"token"
        mock_task.scheduled_time = _make_ts(1002)
        mock_task.started_time = _make_ts(1000)
        client.worker_stub.PollForDecisionTask = AsyncMock(return_value=mock_task)
        worker = DecisionWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        await worker._poll()

        histogram_calls = {c.args[0]: c for c in emitter.histogram.call_args_list}
        assert histogram_calls[DECISION_SCHEDULED_TO_START_LATENCY].args[1] == 0.0

    @pytest.mark.asyncio
    async def test_emits_transient_failed_counter_on_retryable_error(self):
        emitter = _mock_emitter()
        client = _mock_client()
        client.worker_stub.PollForDecisionTask = AsyncMock(
            side_effect=CadenceRpcError("unavailable", StatusCode.UNAVAILABLE)
        )
        worker = DecisionWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        with pytest.raises(CadenceRpcError):
            await worker._poll()

        emitter.counter.assert_any_call(DECISION_POLL_COUNTER, 1, tags=EXPECTED_TAGS)
        emitter.counter.assert_any_call(
            DECISION_POLL_TRANSIENT_FAILED_COUNTER, 1, tags=EXPECTED_TAGS
        )
        assert any(
            c.args[0] == DECISION_POLL_LATENCY for c in emitter.histogram.call_args_list
        )

    @pytest.mark.asyncio
    async def test_emits_failed_counter_on_non_retryable_error(self):
        emitter = _mock_emitter()
        client = _mock_client()
        client.worker_stub.PollForDecisionTask = AsyncMock(
            side_effect=CadenceRpcError("not found", StatusCode.NOT_FOUND)
        )
        worker = DecisionWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        with pytest.raises(CadenceRpcError):
            await worker._poll()

        emitter.counter.assert_any_call(
            DECISION_POLL_FAILED_COUNTER, 1, tags=EXPECTED_TAGS
        )


# ---------------------------------------------------------------------------
# ActivityWorker: run() metrics
# ---------------------------------------------------------------------------


class TestActivityWorkerRunMetrics:
    @pytest.mark.asyncio
    async def test_emits_worker_start_counter(self):
        emitter = _mock_emitter()
        worker = ActivityWorker(
            _mock_client(), TASK_LIST, Registry(), _worker_options(emitter)
        )
        with patch.object(worker._poller, "run", new=AsyncMock()):
            await worker.run()

        emitter.counter.assert_any_call(WORKER_START_COUNTER, 1, tags=EXPECTED_TAGS)
        assert not any(
            call.args[0] == POLLER_START_COUNTER
            for call in emitter.counter.call_args_list
        )

    @pytest.mark.asyncio
    async def test_emits_poller_start_counter_with_configured_count(self):
        emitter = _mock_emitter()
        options = _worker_options(emitter)
        options["activity_task_pollers"] = 5
        worker = ActivityWorker(_mock_client(), TASK_LIST, Registry(), options)
        with patch.object(worker._poller, "_poll_loop", new_callable=AsyncMock):
            await worker.run()

        emitter.counter.assert_any_call(POLLER_START_COUNTER, 5, tags=EXPECTED_TAGS)

    @pytest.mark.asyncio
    async def test_emits_worker_panic_counter_on_exception(self):
        emitter = _mock_emitter()
        worker = ActivityWorker(
            _mock_client(), TASK_LIST, Registry(), _worker_options(emitter)
        )
        with patch.object(
            worker._poller,
            "run",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            with pytest.raises(RuntimeError):
                await worker.run()

        emitter.counter.assert_any_call(WORKER_PANIC_COUNTER, 1, tags=EXPECTED_TAGS)

    @pytest.mark.asyncio
    async def test_no_panic_counter_on_normal_exit(self):
        emitter = _mock_emitter()
        worker = ActivityWorker(
            _mock_client(), TASK_LIST, Registry(), _worker_options(emitter)
        )
        with patch.object(worker._poller, "run", new=AsyncMock()):
            await worker.run()

        calls = [str(c) for c in emitter.counter.call_args_list]
        assert not any(WORKER_PANIC_COUNTER in c for c in calls)


# ---------------------------------------------------------------------------
# ActivityWorker: _poll() metrics
# ---------------------------------------------------------------------------


class TestActivityWorkerPollMetrics:
    @pytest.mark.asyncio
    async def test_emits_poll_counter_and_latency_on_empty_response(self):
        emitter = _mock_emitter()
        client = _mock_client()
        client.worker_stub.PollForActivityTask = AsyncMock(
            return_value=Mock(task_token=b"")
        )
        worker = ActivityWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        result = await worker._poll()

        assert result is None
        emitter.counter.assert_any_call(ACTIVITY_POLL_COUNTER, 1, tags=EXPECTED_TAGS)
        emitter.counter.assert_any_call(
            ACTIVITY_POLL_NO_TASK_COUNTER, 1, tags=EXPECTED_TAGS
        )
        assert any(
            c.args[0] == ACTIVITY_POLL_LATENCY for c in emitter.histogram.call_args_list
        )

    @pytest.mark.asyncio
    async def test_emits_succeed_counter_on_task(self):
        emitter = _mock_emitter()
        client = _mock_client()
        mock_task = Mock()
        mock_task.task_token = b"token"
        mock_task.scheduled_time = _make_ts(0)
        mock_task.started_time = _make_ts(0)
        client.worker_stub.PollForActivityTask = AsyncMock(return_value=mock_task)
        worker = ActivityWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        result = await worker._poll()

        assert result is mock_task
        emitter.counter.assert_any_call(ACTIVITY_POLL_COUNTER, 1, tags=EXPECTED_TAGS)
        emitter.counter.assert_any_call(
            ACTIVITY_POLL_SUCCEED_COUNTER, 1, tags=EXPECTED_TAGS
        )

    @pytest.mark.asyncio
    async def test_emits_scheduled_to_start_latency_when_timestamps_set(self):
        emitter = _mock_emitter()
        client = _mock_client()
        mock_task = Mock()
        mock_task.task_token = b"token"
        mock_task.scheduled_time = _make_ts(500)
        mock_task.started_time = _make_ts(503)
        client.worker_stub.PollForActivityTask = AsyncMock(return_value=mock_task)
        worker = ActivityWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        await worker._poll()

        histogram_calls = {c.args[0]: c for c in emitter.histogram.call_args_list}
        assert ACTIVITY_SCHEDULED_TO_START_LATENCY in histogram_calls
        assert (
            abs(histogram_calls[ACTIVITY_SCHEDULED_TO_START_LATENCY].args[1] - 3.0)
            < 0.01
        )

    @pytest.mark.asyncio
    async def test_emits_scheduled_to_start_latency_when_only_nanos_set(self):
        emitter = _mock_emitter()
        client = _mock_client()
        mock_task = Mock()
        mock_task.task_token = b"token"
        mock_task.scheduled_time = _make_ts(0, 100_000_000)
        mock_task.started_time = _make_ts(0, 300_000_000)
        client.worker_stub.PollForActivityTask = AsyncMock(return_value=mock_task)
        worker = ActivityWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        await worker._poll()

        histogram_calls = {c.args[0]: c for c in emitter.histogram.call_args_list}
        assert (
            abs(histogram_calls[ACTIVITY_SCHEDULED_TO_START_LATENCY].args[1] - 0.2)
            < 0.01
        )

    @pytest.mark.asyncio
    async def test_emits_transient_failed_counter_on_retryable_error(self):
        emitter = _mock_emitter()
        client = _mock_client()
        client.worker_stub.PollForActivityTask = AsyncMock(
            side_effect=CadenceRpcError(
                "resource exhausted", StatusCode.RESOURCE_EXHAUSTED
            )
        )
        worker = ActivityWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        with pytest.raises(CadenceRpcError):
            await worker._poll()

        emitter.counter.assert_any_call(ACTIVITY_POLL_COUNTER, 1, tags=EXPECTED_TAGS)
        emitter.counter.assert_any_call(
            ACTIVITY_POLL_TRANSIENT_FAILED_COUNTER, 1, tags=EXPECTED_TAGS
        )

    @pytest.mark.asyncio
    async def test_emits_failed_counter_on_non_retryable_error(self):
        emitter = _mock_emitter()
        client = _mock_client()
        client.worker_stub.PollForActivityTask = AsyncMock(
            side_effect=CadenceRpcError(
                "permission denied", StatusCode.PERMISSION_DENIED
            )
        )
        worker = ActivityWorker(client, TASK_LIST, Registry(), _worker_options(emitter))

        with pytest.raises(CadenceRpcError):
            await worker._poll()

        emitter.counter.assert_any_call(
            ACTIVITY_POLL_FAILED_COUNTER, 1, tags=EXPECTED_TAGS
        )
