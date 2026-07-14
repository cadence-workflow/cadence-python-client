import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from google.protobuf.duration import from_timedelta
from google.protobuf.timestamp_pb2 import Timestamp

from cadence import workflow
from cadence._internal.activity import ActivityExecutor
from cadence._internal.context_propagation import (
    context_header_from_propagators,
    context_propagation_scope,
    header_to_context_fields,
)
from cadence._internal.workflow.context import Context
from cadence._internal.workflow.workflow_engine import WorkflowEngine
from cadence.api.v1.common_pb2 import (
    ActivityType,
    Header,
    Payload,
    WorkflowExecution,
    WorkflowType,
)
from cadence.api.v1.history_pb2 import (
    DecisionTaskScheduledEventAttributes,
    DecisionTaskStartedEventAttributes,
    HistoryEvent,
    WorkflowExecutionStartedEventAttributes,
)
from cadence.api.v1.service_worker_pb2 import PollForActivityTaskResponse
from cadence.api.v1.service_workflow_pb2 import (
    SignalWithStartWorkflowExecutionResponse,
)
from cadence.client import Client, StartWorkflowOptions
from cadence.context import ContextPropagationError
from cadence.data_converter import DefaultDataConverter
from cadence.testing import TestWorkflowEnvironment
from cadence.worker import Registry, Worker
from cadence.workflow import WorkflowDefinition, WorkflowDefinitionOptions, WorkflowInfo


class _ContextVarPropagator:
    def __init__(self, key: str = "x-request-id") -> None:
        self.key = key
        self.value: ContextVar[str | None] = ContextVar(key, default=None)

    def inject(self) -> dict[str, bytes]:
        value = self.value.get()
        return {} if value is None else {self.key: value.encode()}

    @contextmanager
    def extract(self, headers: Mapping[str, bytes]) -> Iterator[None]:
        raw_value = headers.get(self.key)
        token = self.value.set(raw_value.decode() if raw_value is not None else None)
        try:
            yield
        finally:
            self.value.reset(token)


class _StaticPropagator:
    def __init__(self, fields: dict[str, bytes]) -> None:
        self._fields = fields

    def inject(self) -> dict[str, bytes]:
        return self._fields

    @contextmanager
    def extract(self, _headers: Mapping[str, bytes]) -> Iterator[None]:
        yield


class _BrokenPropagator:
    def inject(self) -> dict[str, bytes]:
        raise ValueError("cannot inject")

    @contextmanager
    def extract(self, headers: Mapping[str, bytes]) -> Iterator[None]:
        if headers:
            yield
            return
        raise ValueError("cannot extract")


class _RecordingPropagator(_StaticPropagator):
    def __init__(self, events: list[str], name: str) -> None:
        super().__init__({})
        self._events = events
        self._name = name

    @contextmanager
    def extract(self, _headers: Mapping[str, bytes]) -> Iterator[None]:
        self._events.append(f"enter:{self._name}")
        try:
            yield
        finally:
            self._events.append(f"exit:{self._name}")


class _CleanupBrokenPropagator(_StaticPropagator):
    @contextmanager
    def extract(self, _headers: Mapping[str, bytes]) -> Iterator[None]:
        try:
            yield
        finally:
            raise ValueError("cannot clean up")


def _workflow_info() -> WorkflowInfo:
    return WorkflowInfo(
        workflow_type="Workflow",
        workflow_domain="domain",
        workflow_id="workflow-id",
        workflow_run_id="run-id",
        workflow_task_list="task-list",
        data_converter=DefaultDataConverter(),
    )


def _activity_task(header: Header | None = None) -> PollForActivityTaskResponse:
    timestamp = Timestamp()
    timestamp.FromJsonString("2020-01-02T03:04:05Z")
    return PollForActivityTaskResponse(
        task_token=b"token",
        workflow_domain="domain",
        workflow_type=WorkflowType(name="Workflow"),
        workflow_execution=WorkflowExecution(
            workflow_id="workflow-id", run_id="run-id"
        ),
        activity_id="activity-id",
        activity_type=ActivityType(name="activity"),
        input=Payload(),
        attempt=1,
        heartbeat_timeout=from_timedelta(timedelta(seconds=1)),
        scheduled_time=timestamp,
        started_time=timestamp,
        start_to_close_timeout=from_timedelta(timedelta(seconds=10)),
        header=header,
    )


def _activity_client() -> MagicMock:
    client = MagicMock(spec=Client)
    client.worker_stub = MagicMock()
    client.worker_stub.RespondActivityTaskCompleted = AsyncMock()
    type(client).data_converter = PropertyMock(return_value=DefaultDataConverter())
    return client


def test_context_header_scope_round_trips_and_restores_contextvar() -> None:
    propagator = _ContextVarPropagator()
    header = Header()
    header.fields["x-request-id"].data = b"request-1"

    with context_propagation_scope((propagator,), header):
        assert propagator.value.get() == "request-1"

    assert propagator.value.get() is None


def test_context_header_preserves_cross_sdk_raw_bytes() -> None:
    header = Header()
    header.fields["go.trace"].data = b"\x00\xffgo"
    header.fields["java.trace"].data = b"\x80java\x00"

    assert header_to_context_fields(header) == {
        "go.trace": b"\x00\xffgo",
        "java.trace": b"\x80java\x00",
    }


def test_context_header_rejects_duplicate_or_invalid_fields() -> None:
    with pytest.raises(ContextPropagationError, match="Multiple context propagators"):
        context_header_from_propagators(
            (
                _StaticPropagator({"shared": b"one"}),
                _StaticPropagator({"shared": b"two"}),
            )
        )

    with pytest.raises(ContextPropagationError, match="non-bytes"):
        context_header_from_propagators(
            (_StaticPropagator(cast(dict[str, bytes], {"invalid": "value"})),)
        )


def test_context_scope_reverses_cleanup_and_wraps_extraction_errors() -> None:
    events: list[str] = []
    first = _RecordingPropagator(events, "first")
    second = _RecordingPropagator(events, "second")
    with context_propagation_scope((first, second), {}):
        assert events == ["enter:first", "enter:second"]
    assert events == ["enter:first", "enter:second", "exit:second", "exit:first"]

    with pytest.raises(ContextPropagationError, match="extract failed"):
        with context_propagation_scope((_BrokenPropagator(),), {}):
            pass

    with pytest.raises(ContextPropagationError, match="cleanup failed"):
        with context_propagation_scope((_CleanupBrokenPropagator({}),), {}):
            pass


def test_worker_propagator_configuration_inherits_or_can_disable() -> None:
    propagator = _ContextVarPropagator()
    client = Client(
        domain="domain",
        target="localhost:7933",
        context_propagators=[propagator],
    )

    inherited = Worker(
        client,
        "task-list",
        Registry(),
        disable_workflow_worker=True,
        disable_activity_worker=True,
    )
    disabled = Worker(
        client,
        "task-list",
        Registry(),
        disable_workflow_worker=True,
        disable_activity_worker=True,
        context_propagators=(),
    )

    assert inherited._options["context_propagators"] == (propagator,)
    assert disabled._options["context_propagators"] == ()


def test_client_start_request_includes_context_header() -> None:
    propagator = _ContextVarPropagator()
    token = propagator.value.set("client-request")
    try:
        client = Client(
            domain="domain",
            target="localhost:7933",
            context_propagators=(propagator,),
        )
        request = client._build_start_workflow_request(
            "Workflow",
            (),
            StartWorkflowOptions(
                task_list="task-list",
                execution_start_to_close_timeout=timedelta(minutes=1),
                task_start_to_close_timeout=timedelta(seconds=10),
            ),
        )
    finally:
        propagator.value.reset(token)

    assert request.header.fields["x-request-id"].data == b"client-request"


@pytest.mark.asyncio
async def test_signal_with_start_reuses_the_start_header() -> None:
    propagator = _ContextVarPropagator()
    client = Client(
        domain="domain",
        target="localhost:7933",
        context_propagators=(propagator,),
    )
    client._workflow_stub.SignalWithStartWorkflowExecution = AsyncMock(
        return_value=SignalWithStartWorkflowExecutionResponse(run_id="run-id")
    )
    token = propagator.value.set("signal-start")
    try:
        await client.signal_with_start_workflow(
            "Workflow",
            "signal",
            [],
            task_list="task-list",
            execution_start_to_close_timeout=timedelta(minutes=1),
        )
    finally:
        propagator.value.reset(token)

    request = client._workflow_stub.SignalWithStartWorkflowExecution.call_args.args[0]
    assert request.start_request.header.fields["x-request-id"].data == b"signal-start"


def test_client_injection_failure_happens_before_rpc() -> None:
    client = Client(
        domain="domain",
        target="localhost:7933",
        context_propagators=(_BrokenPropagator(),),
    )
    with pytest.raises(ContextPropagationError, match="inject failed"):
        client._build_start_workflow_request(
            "Workflow",
            (),
            StartWorkflowOptions(
                task_list="task-list",
                execution_start_to_close_timeout=timedelta(minutes=1),
                task_start_to_close_timeout=timedelta(seconds=10),
            ),
        )


@pytest.mark.asyncio
async def test_workflow_context_injects_activity_and_child_headers() -> None:
    propagator = _ContextVarPropagator()
    decision_manager = MagicMock()
    loop = asyncio.get_running_loop()
    activity_result = loop.create_future()
    activity_result.set_result(Payload(data=b'"ok"'))
    decision_manager.schedule_activity.return_value = activity_result

    context = Context(_workflow_info(), decision_manager, (propagator,))
    with context_propagation_scope((propagator,), {"x-request-id": b"workflow"}):
        await context.execute_activity(
            "activity",
            str,
            schedule_to_close_timeout=timedelta(seconds=10),
        )
        child_attrs = context._build_child_workflow_attrs(
            "Child",
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

    activity_attrs = decision_manager.schedule_activity.call_args.args[0]
    assert activity_attrs.header.fields["x-request-id"].data == b"workflow"
    assert child_attrs.header.fields["x-request-id"].data == b"workflow"


@pytest.mark.asyncio
async def test_activity_context_is_scoped_for_async_and_sync_activities() -> None:
    propagator = _ContextVarPropagator()
    async_client = _activity_client()
    sync_client = _activity_client()
    registry = Registry()
    observed_async: list[str | None] = []
    observed_sync: list[str | None] = []

    @registry.activity(name="activity")
    async def async_activity() -> str:
        observed_async.append(propagator.value.get())
        return "async"

    async_executor = ActivityExecutor(
        async_client,
        "task-list",
        "identity",
        1,
        registry.get_activity,
        context_propagators=(propagator,),
    )
    first_header = Header()
    first_header.fields["x-request-id"].data = b"first"
    await async_executor.execute(_activity_task(first_header))
    await async_executor.execute(_activity_task())

    sync_registry = Registry()

    @sync_registry.activity(name="activity")
    def sync_activity() -> str:
        observed_sync.append(propagator.value.get())
        return "sync"

    sync_executor = ActivityExecutor(
        sync_client,
        "task-list",
        "identity",
        1,
        sync_registry.get_activity,
        context_propagators=(propagator,),
    )
    sync_header = Header()
    sync_header.fields["x-request-id"].data = b"sync"
    await sync_executor.execute(_activity_task(sync_header))

    assert observed_async == ["first", None]
    assert observed_sync == ["sync"]
    assert propagator.value.get() is None


def test_continue_as_new_preserves_workflow_context_header() -> None:
    propagator = _ContextVarPropagator()

    class ContinueWorkflow:
        @workflow.run
        async def run(self) -> None:
            workflow.continue_as_new("next")

    definition = WorkflowDefinition.wrap(
        ContinueWorkflow, WorkflowDefinitionOptions(name="ContinueWorkflow")
    )
    header = Header()
    header.fields["x-request-id"].data = b"continued"
    events = [
        HistoryEvent(
            event_id=1,
            workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                header=header
            ),
        ),
        HistoryEvent(
            event_id=2,
            decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
        ),
        HistoryEvent(
            event_id=3,
            decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                scheduled_event_id=2
            ),
        ),
    ]

    result = WorkflowEngine(
        _workflow_info(),
        definition,
        context_propagators=(propagator,),
        start_header=header,
    ).process_decision(events)

    attrs = result.decisions[0].continue_as_new_workflow_execution_decision_attributes
    assert attrs.header.fields["x-request-id"].data == b"continued"


@pytest.mark.asyncio
async def test_test_workflow_environment_scopes_start_context() -> None:
    propagator = _ContextVarPropagator()
    registry = Registry()

    @registry.workflow()
    class ContextWorkflow:
        @workflow.run
        async def run(self) -> str:
            return propagator.value.get() or ""

    with TestWorkflowEnvironment(registry, context_propagators=(propagator,)) as env:
        token = propagator.value.set("test-environment")
        try:
            await env.client.start_workflow("ContextWorkflow", task_list="test")
        finally:
            propagator.value.reset(token)

        assert env.get_workflow_result(str) == "test-environment"


@pytest.mark.asyncio
async def test_test_workflow_environment_propagates_activity_and_continue_as_new() -> (
    None
):
    propagator = _ContextVarPropagator()
    registry = Registry()
    observed_activity: list[str | None] = []

    @registry.workflow()
    class ContextWorkflow:
        @workflow.run
        async def run(self, continued: bool = False) -> str:
            if not continued:
                workflow.continue_as_new(True)
            return await workflow.execute_activity("activity", str)

    def activity() -> str:
        observed_activity.append(propagator.value.get())
        return "done"

    with TestWorkflowEnvironment(registry, context_propagators=(propagator,)) as env:
        env.on_activity("activity", fn=activity)
        token = propagator.value.set("test-environment")
        try:
            await env.client.start_workflow("ContextWorkflow", task_list="test")
        finally:
            propagator.value.reset(token)

        assert env.get_workflow_result(str) == "done"
        assert observed_activity == ["test-environment"]
