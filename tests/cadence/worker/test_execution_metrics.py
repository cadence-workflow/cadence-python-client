"""Tests for decision task execution and workflow lifecycle metrics."""

import asyncio
import time
from typing import cast
import pytest
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from google.protobuf.timestamp_pb2 import Timestamp

from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.decision_pb2 import (
    Decision,
    CompleteWorkflowExecutionDecisionAttributes,
    FailWorkflowExecutionDecisionAttributes,
    ContinueAsNewWorkflowExecutionDecisionAttributes,
)
from cadence.api.v1.history_pb2 import HistoryEvent, History
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.client import Client
from cadence.data_converter import DefaultDataConverter
from cadence.metrics import MetricsEmitter
from cadence.metrics.constants import (
    DECISION_EXECUTION_FAILED_COUNTER,
    DECISION_EXECUTION_LATENCY,
    DECISION_RESPONSE_FAILED_COUNTER,
    DECISION_RESPONSE_LATENCY,
    DECISION_TASK_COMPLETED_COUNTER,
    DECISION_TASK_PANIC_COUNTER,
    TAG_DOMAIN,
    TAG_TASK_LIST,
    TAG_WORKFLOW_TYPE,
    WORKFLOW_CANCELED_COUNTER,
    WORKFLOW_COMPLETED_COUNTER,
    WORKFLOW_CONTINUE_AS_NEW_COUNTER,
    WORKFLOW_END_TO_END_LATENCY,
    WORKFLOW_FAILED_COUNTER,
    WORKFLOW_GET_HISTORY_COUNTER,
    WORKFLOW_GET_HISTORY_LATENCY,
)
from cadence.worker._decision_task_handler import DecisionTaskHandler
from cadence.worker._registry import Registry
from cadence._internal.workflow.workflow_engine import (
    DecisionResult,
    _outcome_from_decision,
)

DOMAIN = "test-domain"
TASK_LIST = "test-tl"
WF_TYPE = "TestWorkflow"
EXPECTED_TAGS = {
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


def _make_started_event(event_time_seconds: int = 0) -> HistoryEvent:
    from cadence.api.v1.history_pb2 import WorkflowExecutionStartedEventAttributes

    ev = HistoryEvent(
        workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes()
    )
    ev.event_time.seconds = event_time_seconds
    return ev


def _mock_client() -> Mock:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value=DOMAIN)
    type(client).identity = PropertyMock(return_value="test-id")
    client.data_converter = DefaultDataConverter()
    stub = Mock()
    stub.RespondDecisionTaskCompleted = AsyncMock()
    stub.RespondDecisionTaskFailed = AsyncMock()
    stub.RespondQueryTaskCompleted = AsyncMock()
    client.worker_stub = stub
    client.workflow_stub = Mock()
    return client


def _make_task(with_query: bool = False) -> Mock:
    task = Mock(spec=PollForDecisionTaskResponse)
    task.task_token = b"token"
    task.workflow_execution = Mock()
    task.workflow_execution.workflow_id = "wf-id"
    task.workflow_execution.run_id = "run-id"
    task.workflow_type = Mock()
    task.workflow_type.name = WF_TYPE
    task.started_event_id = 1
    task.attempt = 0
    task.next_page_token = b""
    task.HasField = Mock(side_effect=lambda f: f == "query" if with_query else False)
    if with_query:
        task.query = Mock()
        task.query.query_type = "MyQuery"
        task.query.query_args = None
    started = _make_started_event()
    task.history = History(events=[started])
    return task


def _make_handler(emitter=None, registry=None) -> DecisionTaskHandler:
    client = _mock_client()
    if registry is None:
        registry = Registry()
    return DecisionTaskHandler(
        client=client,
        task_list=TASK_LIST,
        registry=registry,
        identity="test-id",
        metrics_emitter=emitter or _mock_emitter(),
    )


def _mock_registry() -> Mock:
    reg = Mock(spec=Registry)
    reg.get_workflow = Mock(return_value=Mock())
    return reg


# ---------------------------------------------------------------------------
# _outcome_from_decision helper
# ---------------------------------------------------------------------------


class TestOutcomeFromDecision:
    def test_completed(self):
        d = Decision(
            complete_workflow_execution_decision_attributes=CompleteWorkflowExecutionDecisionAttributes()
        )
        assert _outcome_from_decision(d) == "completed"

    def test_failed(self):
        from cadence.api.v1.common_pb2 import Failure

        d = Decision(
            fail_workflow_execution_decision_attributes=FailWorkflowExecutionDecisionAttributes(
                failure=Failure(reason="oops")
            )
        )
        assert _outcome_from_decision(d) == "failed"

    def test_continue_as_new(self):
        from cadence.api.v1.common_pb2 import WorkflowType

        d = Decision(
            continue_as_new_workflow_execution_decision_attributes=ContinueAsNewWorkflowExecutionDecisionAttributes(
                workflow_type=WorkflowType(name="MyWf")
            )
        )
        assert _outcome_from_decision(d) == "continue_as_new"

    def test_unknown_returns_none(self):
        d = Decision()
        assert _outcome_from_decision(d) is None


# ---------------------------------------------------------------------------
# DecisionTaskHandler: execution metrics
# ---------------------------------------------------------------------------


class TestDecisionExecutionMetrics:
    @pytest.mark.asyncio
    async def test_emits_execution_latency_on_success(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter, _mock_registry())
        task = _make_task()
        dr = DecisionResult(decisions=[])

        with (
            patch(
                "cadence.worker._decision_task_handler.iterate_history_events",
                return_value=_async_iter([_make_started_event()]),
            ),
            patch("cadence.worker._decision_task_handler.WorkflowEngine"),
            patch.object(handler, "_respond_decision_task_completed", new=AsyncMock()),
        ):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new=AsyncMock(return_value=dr)):
                await handler._handle_task_implementation(task)

        emitter.with_tags.assert_called_once_with(EXPECTED_TAGS)
        histogram_names = [c.args[0] for c in _tagged(emitter).histogram.call_args_list]
        assert DECISION_EXECUTION_LATENCY in histogram_names

    @pytest.mark.asyncio
    async def test_emits_execution_failed_counter_on_engine_error(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter, _mock_registry())
        task = _make_task()

        with (
            patch(
                "cadence.worker._decision_task_handler.iterate_history_events",
                return_value=_async_iter([_make_started_event()]),
            ),
            patch("cadence.worker._decision_task_handler.WorkflowEngine"),
        ):
            loop = asyncio.get_event_loop()
            with patch.object(
                loop,
                "run_in_executor",
                new=AsyncMock(side_effect=RuntimeError("engine boom")),
            ):
                with pytest.raises(RuntimeError):
                    await handler._handle_task_implementation(task)

        _tagged(emitter).counter.assert_any_call(DECISION_EXECUTION_FAILED_COUNTER)
        histogram_names = [c.args[0] for c in _tagged(emitter).histogram.call_args_list]
        assert DECISION_EXECUTION_LATENCY in histogram_names


# ---------------------------------------------------------------------------
# DecisionTaskHandler: response metrics
# ---------------------------------------------------------------------------


class TestDecisionResponseMetrics:
    @pytest.mark.asyncio
    async def test_emits_response_latency_and_completed_counter_on_success(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        task = _make_task()
        dr = DecisionResult(decisions=[])

        await handler._respond_decision_task_completed(task, dr, emitter)

        counter_names = [c.args[0] for c in emitter.counter.call_args_list]
        histogram_names = [c.args[0] for c in emitter.histogram.call_args_list]
        assert DECISION_TASK_COMPLETED_COUNTER in counter_names
        assert DECISION_RESPONSE_LATENCY in histogram_names

    @pytest.mark.asyncio
    async def test_emits_response_failed_counter_on_rpc_error(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        handler._client.worker_stub.RespondDecisionTaskCompleted = AsyncMock(
            side_effect=RuntimeError("rpc failed")
        )
        task = _make_task()
        dr = DecisionResult(decisions=[])

        with pytest.raises(RuntimeError):
            await handler._respond_decision_task_completed(task, dr, emitter)

        counter_names = [c.args[0] for c in emitter.counter.call_args_list]
        histogram_names = [c.args[0] for c in emitter.histogram.call_args_list]
        assert DECISION_RESPONSE_FAILED_COUNTER in counter_names
        # Response latency is still recorded on failure (finally block).
        assert DECISION_RESPONSE_LATENCY in histogram_names

    @pytest.mark.asyncio
    async def test_falls_back_to_default_emitter_when_none_passed(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        task = _make_task()
        dr = DecisionResult(decisions=[])

        await handler._respond_decision_task_completed(task, dr)

        counter_names = [c.args[0] for c in emitter.counter.call_args_list]
        assert DECISION_TASK_COMPLETED_COUNTER in counter_names

    @pytest.mark.asyncio
    async def test_query_completion_emits_no_counter(self):
        # Go/Java don't track query completions; DECISION_TASK_FORCE_COMPLETED
        # means something unrelated there (decision-heartbeat force-complete).
        from cadence.api.v1.query_pb2 import (
            WorkflowQueryResult,
            QUERY_RESULT_TYPE_ANSWERED,
        )

        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        task = _make_task(with_query=True)
        result = WorkflowQueryResult(result_type=QUERY_RESULT_TYPE_ANSWERED)

        await handler._respond_query_task_completed(task, result)

        emitter.counter.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_workflow_outcome_metrics_emitted_when_respond_fails(self):
        # Regression: outcome metrics must not fire if the RPC to persist the decision fails.
        emitter = _mock_emitter()
        handler = _make_handler(emitter, _mock_registry())
        task = _make_task()
        dr = DecisionResult(
            decisions=[
                Decision(
                    complete_workflow_execution_decision_attributes=CompleteWorkflowExecutionDecisionAttributes()
                )
            ]
        )

        with (
            patch(
                "cadence.worker._decision_task_handler.iterate_history_events",
                return_value=_async_iter([_make_started_event()]),
            ),
            patch("cadence.worker._decision_task_handler.WorkflowEngine"),
        ):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "run_in_executor", new=AsyncMock(return_value=dr)):
                # Make the respond RPC fail
                handler._client.worker_stub.RespondDecisionTaskCompleted = AsyncMock(
                    side_effect=RuntimeError("rpc failed")
                )
                with pytest.raises(RuntimeError):
                    await handler._handle_task_implementation(task)

        counter_names = [c.args[0] for c in _tagged(emitter).counter.call_args_list]
        assert WORKFLOW_COMPLETED_COUNTER not in counter_names
        assert WORKFLOW_END_TO_END_LATENCY not in [
            c.args[0] for c in _tagged(emitter).histogram.call_args_list
        ]


# ---------------------------------------------------------------------------
# DecisionTaskHandler: panic and workflow lifecycle metrics
# ---------------------------------------------------------------------------


class TestDecisionPanicAndLifecycleMetrics:
    @pytest.mark.asyncio
    async def test_handle_task_failure_does_not_emit_panic_counter(self):
        # DECISION_TASK_PANIC_COUNTER is scoped to workflow-engine execution
        # failures (matches Go's "decider panic"), not every decision-task
        # failure reason (e.g. unregistered workflow type, RPC errors).
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        task = _make_task()

        await handler.handle_task_failure(task, RuntimeError("boom"))

        counter_names = [c.args[0] for c in emitter.counter.call_args_list]
        assert DECISION_TASK_PANIC_COUNTER not in counter_names

    @pytest.mark.asyncio
    async def test_emits_panic_counter_on_workflow_engine_execution_failure(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter, _mock_registry())
        task = _make_task()

        with (
            patch(
                "cadence.worker._decision_task_handler.iterate_history_events",
                return_value=_async_iter([_make_started_event()]),
            ),
            patch("cadence.worker._decision_task_handler.WorkflowEngine"),
        ):
            loop = asyncio.get_event_loop()
            with patch.object(
                loop,
                "run_in_executor",
                new=AsyncMock(side_effect=RuntimeError("engine boom")),
            ):
                with pytest.raises(RuntimeError):
                    await handler._handle_task_implementation(task)

        counter_names = [c.args[0] for c in _tagged(emitter).counter.call_args_list]
        assert DECISION_TASK_PANIC_COUNTER in counter_names

    def test_emits_completed_counter_for_completed_outcome(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        events = [_make_started_event(event_time_seconds=0)]

        handler._emit_workflow_outcome_metrics("completed", events, emitter)

        counter_names = [c.args[0] for c in emitter.counter.call_args_list]
        assert WORKFLOW_COMPLETED_COUNTER in counter_names

    def test_emits_failed_counter_for_failed_outcome(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        handler._emit_workflow_outcome_metrics("failed", [], emitter)
        counter_names = [c.args[0] for c in emitter.counter.call_args_list]
        assert WORKFLOW_FAILED_COUNTER in counter_names

    def test_emits_canceled_counter_for_canceled_outcome(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        handler._emit_workflow_outcome_metrics("canceled", [], emitter)
        counter_names = [c.args[0] for c in emitter.counter.call_args_list]
        assert WORKFLOW_CANCELED_COUNTER in counter_names

    def test_emits_continue_as_new_counter(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        handler._emit_workflow_outcome_metrics("continue_as_new", [], emitter)
        counter_names = [c.args[0] for c in emitter.counter.call_args_list]
        assert WORKFLOW_CONTINUE_AS_NEW_COUNTER in counter_names

    def test_emits_end_to_end_latency_when_event_time_set(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        started = _make_started_event(event_time_seconds=int(time.time()) - 10)

        handler._emit_workflow_outcome_metrics("completed", [started], emitter)

        histogram_names = [c.args[0] for c in emitter.histogram.call_args_list]
        assert WORKFLOW_END_TO_END_LATENCY in histogram_names
        latency_call = next(
            c
            for c in emitter.histogram.call_args_list
            if c.args[0] == WORKFLOW_END_TO_END_LATENCY
        )
        assert 5e9 < latency_call.args[1] < 20e9

    def test_no_end_to_end_latency_when_event_time_zero(self):
        emitter = _mock_emitter()
        handler = _make_handler(emitter)
        started = _make_started_event(event_time_seconds=0)

        handler._emit_workflow_outcome_metrics("completed", [started], emitter)

        histogram_names = [c.args[0] for c in emitter.histogram.call_args_list]
        assert WORKFLOW_END_TO_END_LATENCY not in histogram_names


# ---------------------------------------------------------------------------
# iterate_history_events: paginated fetch metrics
# ---------------------------------------------------------------------------


class TestHistoryFetchMetrics:
    @pytest.mark.asyncio
    async def test_emits_get_history_metrics_per_page(self):
        from cadence._internal.workflow.history_event_iterator import (
            iterate_history_events,
        )
        from cadence.api.v1.service_workflow_pb2 import (
            GetWorkflowExecutionHistoryResponse,
        )
        from cadence.api.v1.history_pb2 import History

        emitter = _mock_emitter()

        client = _mock_client()
        second_page_response = GetWorkflowExecutionHistoryResponse(
            history=History(events=[_make_started_event()]),
            next_page_token=b"",
        )
        client.workflow_stub.GetWorkflowExecutionHistory = AsyncMock(
            return_value=second_page_response
        )

        # Build a Mock task but with a real WorkflowExecution so protobuf construction works
        task = _make_task()
        task.workflow_execution = WorkflowExecution(workflow_id="wf-1", run_id="run-1")
        task.next_page_token = b"page-token"

        events = [e async for e in iterate_history_events(task, client, emitter)]

        assert len(events) == 2
        emitter.counter.assert_any_call(WORKFLOW_GET_HISTORY_COUNTER)
        histogram_names = [c.args[0] for c in emitter.histogram.call_args_list]
        assert WORKFLOW_GET_HISTORY_LATENCY in histogram_names

    @pytest.mark.asyncio
    async def test_no_metrics_emitted_for_single_page(self):
        from cadence._internal.workflow.history_event_iterator import (
            iterate_history_events,
        )

        emitter = _mock_emitter()
        client = _mock_client()
        task = _make_task()  # next_page_token = b"" → no RPC

        events = [e async for e in iterate_history_events(task, client, emitter)]

        assert len(events) == 1
        emitter.counter.assert_not_called()
        emitter.histogram.assert_not_called()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_iter(items):
    for item in items:
        yield item
