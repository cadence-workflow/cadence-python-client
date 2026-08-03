from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock

import pytest

from cadence import workflow
from cadence._internal.context import (
    extract_headers,
    header_from_dict,
    header_to_dict,
    inject_headers,
)
from cadence._internal.workflow.workflow_engine import WorkflowEngine
from cadence.api.v1.common_pb2 import ActivityType, Header, Payload
from cadence.api.v1.history_pb2 import (
    ActivityTaskCompletedEventAttributes,
    ActivityTaskScheduledEventAttributes,
    ActivityTaskStartedEventAttributes,
    DecisionTaskCompletedEventAttributes,
    DecisionTaskScheduledEventAttributes,
    DecisionTaskStartedEventAttributes,
    HistoryEvent,
    WorkflowExecutionStartedEventAttributes,
)
from cadence.api.v1.service_workflow_pb2 import (
    SignalWithStartWorkflowExecutionResponse,
    StartWorkflowExecutionResponse,
)
from cadence.client import Client, ClientOptions
from cadence.client import (
    _validate_and_copy_defaults as _validate_and_copy_client_defaults,
)
from cadence.context import ContextVarPropagator
from cadence.data_converter import DefaultDataConverter
from cadence.metrics import NoOpMetricsEmitter
from cadence.testing import TestWorkflowEnvironment
from cadence.worker._types import WorkerOptions
from cadence.worker._worker import _validate_and_copy_defaults
from cadence.worker import Registry
from cadence.workflow import WorkflowDefinition, WorkflowDefinitionOptions, WorkflowInfo


def _string_propagator(
    var: ContextVar[str], header_key: str = "context"
) -> ContextVarPropagator[str]:
    return ContextVarPropagator(
        var, header_key, lambda value: value.encode(), bytes.decode
    )


def test_context_var_propagator_unset_restores_and_nests() -> None:
    value: ContextVar[str] = ContextVar("value")
    propagator = _string_propagator(value)

    assert propagator.inject() == {}
    root = value.set("root")
    try:
        assert propagator.inject() == {"context": b"root"}
        with propagator.extract({"context": b"outer"}):
            assert value.get() == "outer"
            with propagator.extract({"context": b"inner"}):
                assert value.get() == "inner"
            assert value.get() == "outer"
        assert value.get() == "root"
        with propagator.extract({}):
            assert value.get() == "root"
    finally:
        value.reset(root)


def test_header_conversion_and_ordered_injection() -> None:
    assert header_from_dict({}) is None
    header = Header(fields={"binary": Payload(data=b"\x00\xff"), "empty": Payload()})
    assert header_to_dict(header) == {"binary": b"\x00\xff", "empty": b""}

    class Propagator:
        def __init__(self, result: Mapping[str, bytes]) -> None:
            self.result = result

        def inject(self) -> Mapping[str, bytes]:
            return self.result

        @contextmanager
        def extract(self, headers: Mapping[str, bytes]) -> Iterator[None]:
            yield

    assert inject_headers(
        (Propagator({"first": b"1", "same": b"old"}), Propagator({"same": b"new"}))
    ) == {"first": b"1", "same": b"new"}


def test_extract_passes_full_headers_and_unwinds_partial_failure() -> None:
    entered: list[str] = []

    class Propagator:
        def __init__(self, name: str, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        def inject(self) -> Mapping[str, bytes]:
            return {}

        @contextmanager
        def extract(self, headers: Mapping[str, bytes]) -> Iterator[None]:
            assert headers == {"all": b"headers"}
            entered.append(f"enter:{self.name}")
            if self.fail:
                raise RuntimeError("extract failed")
            try:
                yield
            finally:
                entered.append(f"exit:{self.name}")

    with pytest.raises(RuntimeError, match="extract failed"):
        with extract_headers(
            (Propagator("one"), Propagator("two", fail=True)), {"all": b"headers"}
        ):
            pass
    assert entered == ["enter:one", "enter:two", "exit:one"]


@pytest.mark.asyncio
async def test_client_injects_start_and_signal_with_start_headers() -> None:
    value: ContextVar[str] = ContextVar("client-context")
    propagator = _string_propagator(value)
    client = object.__new__(Client)
    client._options = {
        "domain": "domain",
        "target": "target",
        "data_converter": DefaultDataConverter(),
        "identity": "identity",
        "metrics_emitter": NoOpMetricsEmitter(),
        "context_propagators": (propagator,),
    }
    client._workflow_stub = type(
        "WorkflowStub",
        (),
        {
            "StartWorkflowExecution": AsyncMock(
                return_value=StartWorkflowExecutionResponse(run_id="start-run")
            ),
            "SignalWithStartWorkflowExecution": AsyncMock(
                return_value=SignalWithStartWorkflowExecutionResponse(
                    run_id="signal-start-run"
                )
            ),
        },
    )()

    token = value.set("client")
    try:
        await client.start_workflow(
            "workflow",
            task_list="task-list",
            execution_start_to_close_timeout=timedelta(seconds=1),
        )
        await client.signal_with_start_workflow(
            "workflow",
            "signal",
            [],
            task_list="task-list",
            execution_start_to_close_timeout=timedelta(seconds=1),
        )
    finally:
        value.reset(token)

    start_request = client.workflow_stub.StartWorkflowExecution.call_args.args[0]
    signal_start_request = (
        client.workflow_stub.SignalWithStartWorkflowExecution.call_args.args[0]
    )
    assert header_to_dict(start_request.header) == {"context": b"client"}
    assert header_to_dict(signal_start_request.start_request.header) == {
        "context": b"client"
    }


def test_client_defaults_to_no_propagators_and_snapshots_mutable_sequence() -> None:
    value: ContextVar[str] = ContextVar("client-default-context")
    propagator = _string_propagator(value)

    defaulted = _validate_and_copy_client_defaults(
        ClientOptions(domain="domain", target="target")
    )
    assert defaulted["context_propagators"] == ()

    mutable = [propagator]
    snapshotted = _validate_and_copy_client_defaults(
        ClientOptions(domain="domain", target="target", context_propagators=mutable)
    )
    mutable.append(_string_propagator(value, "other"))
    assert snapshotted["context_propagators"] == (propagator,)


def test_worker_context_propagators_inherit_and_allow_override() -> None:
    value: ContextVar[str] = ContextVar("worker-context")
    propagator = _string_propagator(value)
    override_propagator = _string_propagator(value, "override")
    client = object.__new__(Client)
    client._options = {
        "identity": "client",
        "metrics_emitter": NoOpMetricsEmitter(),
        "context_propagators": (propagator,),
    }

    inherited = WorkerOptions()
    _validate_and_copy_defaults(client, "task-list", inherited)
    assert inherited["context_propagators"] == (propagator,)

    replaced = WorkerOptions(context_propagators=[override_propagator])
    _validate_and_copy_defaults(client, "task-list", replaced)
    assert replaced["context_propagators"] == (override_propagator,)

    disabled = WorkerOptions(context_propagators=[])
    _validate_and_copy_defaults(client, "task-list", disabled)
    assert disabled["context_propagators"] == ()


def test_production_workflow_started_header_reaches_activity_decision() -> None:
    value: ContextVar[str] = ContextVar("production-activity-context")
    propagator = _string_propagator(value)
    observed: list[str] = []

    class Workflow:
        @workflow.run
        async def run(self) -> None:
            observed.append(value.get())
            await workflow.execute_activity(
                "activity",
                str,
                schedule_to_close_timeout=timedelta(seconds=1),
            )

    events = _started_events({"context": b"from-start"})
    result = _production_engine(
        Workflow,
        propagator,
        header_to_dict(events[0].workflow_execution_started_event_attributes.header),
    ).process_decision(events)

    assert observed == ["from-start"]
    attrs = result.decisions[0].schedule_activity_task_decision_attributes
    assert header_to_dict(attrs.header) == {"context": b"from-start"}
    with pytest.raises(LookupError):
        value.get()


def test_production_workflow_started_header_reaches_child_decision() -> None:
    value: ContextVar[str] = ContextVar("production-child-context")
    propagator = _string_propagator(value)
    observed: list[str] = []

    class Workflow:
        @workflow.run
        async def run(self) -> None:
            observed.append(value.get())
            await workflow.execute_child_workflow(
                "child",
                str,
                execution_start_to_close_timeout=timedelta(seconds=1),
            )

    events = _started_events({"context": b"from-start"})
    result = _production_engine(
        Workflow,
        propagator,
        header_to_dict(events[0].workflow_execution_started_event_attributes.header),
    ).process_decision(events)

    assert observed == ["from-start"]
    attrs = result.decisions[0].start_child_workflow_execution_decision_attributes
    assert header_to_dict(attrs.header) == {"context": b"from-start"}
    with pytest.raises(LookupError):
        value.get()


def test_production_workflow_continue_as_new_injects_header() -> None:
    value: ContextVar[str] = ContextVar("production-continue-context")
    propagator = _string_propagator(value)

    class Workflow:
        @workflow.run
        async def run(self) -> None:
            workflow.continue_as_new()

    events = _started_events({"context": b"from-start"})
    result = _production_engine(
        Workflow,
        propagator,
        header_to_dict(events[0].workflow_execution_started_event_attributes.header),
    ).process_decision(events)

    attrs = result.decisions[0].continue_as_new_workflow_execution_decision_attributes
    assert header_to_dict(attrs.header) == {"context": b"from-start"}
    with pytest.raises(LookupError):
        value.get()


def test_replay_restores_context_each_decision_despite_header_drift() -> None:
    value: ContextVar[str] = ContextVar("replay-context")
    propagator = _string_propagator(value)
    observed: list[str] = []

    class Workflow:
        @workflow.run
        async def run(self) -> str:
            observed.append(value.get())
            result = await workflow.execute_activity(
                "activity",
                str,
                schedule_to_close_timeout=timedelta(seconds=1),
            )
            observed.append(value.get())
            return result

    engine = _production_engine(Workflow, propagator, {"context": b"from-start"})

    first = engine.process_decision(_started_events({"context": b"from-start"}))
    scheduled = first.decisions[0].schedule_activity_task_decision_attributes
    assert header_to_dict(scheduled.header) == {"context": b"from-start"}

    # The recorded schedule carries a different header than this worker injects now,
    # which must not be treated as a nondeterministic replay.
    second = engine.process_decision(
        _activity_completion_events(
            activity_id=scheduled.activity_id,
            recorded_headers={"context": b"recorded-elsewhere"},
            result="activity-result",
        )
    )

    assert observed == ["from-start", "from-start"]
    completed = second.decisions[0].complete_workflow_execution_decision_attributes
    assert DefaultDataConverter().from_data(completed.result, [str]) == [
        "activity-result"
    ]
    with pytest.raises(LookupError):
        value.get()


@pytest.mark.asyncio
async def test_test_environment_propagates_client_workflow_activity_and_child() -> None:
    value: ContextVar[str] = ContextVar("test-environment-context")
    propagator = _string_propagator(value)
    registry = Registry()

    @registry.activity(name="read-context")
    async def read_context() -> str:
        return value.get()

    @registry.workflow
    class Child:
        @workflow.run
        async def run(self) -> str:
            return value.get()

    @registry.workflow
    class Parent:
        @workflow.run
        async def run(self) -> str:
            activity_value = await workflow.execute_activity(
                "read-context",
                str,
                schedule_to_close_timeout=timedelta(seconds=1),
            )
            child_value = await workflow.execute_child_workflow(
                "Child",
                str,
                execution_start_to_close_timeout=timedelta(seconds=1),
            )
            return f"{value.get()}:{activity_value}:{child_value}"

    with TestWorkflowEnvironment(
        registry, context_propagators=(propagator,)
    ) as environment:
        token = value.set("client")
        try:
            await environment.client.start_workflow("Parent", task_list="test")
        finally:
            value.reset(token)

        assert environment.get_workflow_result(str) == "client:client:client"
        with pytest.raises(LookupError):
            value.get()


def _started_events(headers: Mapping[str, bytes]) -> list[HistoryEvent]:
    started = WorkflowExecutionStartedEventAttributes(header=header_from_dict(headers))
    events = [
        HistoryEvent(workflow_execution_started_event_attributes=started),
        HistoryEvent(
            decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes()
        ),
        HistoryEvent(
            decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                scheduled_event_id=2
            )
        ),
    ]
    for event_id, event in enumerate(events, start=1):
        event.event_id = event_id
        event.event_time.FromDatetime(datetime.fromtimestamp(event_id, tz=timezone.utc))
    return events


def _activity_completion_events(
    activity_id: str, recorded_headers: Mapping[str, bytes], result: str
) -> list[HistoryEvent]:
    """Replay the first decision's output, then deliver the activity result."""
    events = [
        HistoryEvent(
            event_id=4,
            decision_task_completed_event_attributes=DecisionTaskCompletedEventAttributes(
                scheduled_event_id=2, started_event_id=3
            ),
        ),
        HistoryEvent(
            event_id=5,
            activity_task_scheduled_event_attributes=ActivityTaskScheduledEventAttributes(
                activity_id=activity_id,
                activity_type=ActivityType(name="activity"),
                header=header_from_dict(recorded_headers),
            ),
        ),
        HistoryEvent(
            event_id=6,
            activity_task_started_event_attributes=ActivityTaskStartedEventAttributes(
                scheduled_event_id=5
            ),
        ),
        HistoryEvent(
            event_id=7,
            activity_task_completed_event_attributes=ActivityTaskCompletedEventAttributes(
                scheduled_event_id=5,
                result=DefaultDataConverter().to_data([result]),
            ),
        ),
        HistoryEvent(
            event_id=8,
            decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
        ),
        HistoryEvent(
            event_id=9,
            decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                scheduled_event_id=8
            ),
        ),
    ]
    for event in events:
        event.event_time.FromDatetime(
            datetime.fromtimestamp(event.event_id, tz=timezone.utc)
        )
    return events


def _production_engine(
    workflow_class: type,
    propagator: ContextVarPropagator[str],
    headers: Mapping[str, bytes],
) -> WorkflowEngine:
    return WorkflowEngine(
        info=WorkflowInfo(
            workflow_type="workflow",
            workflow_domain="domain",
            workflow_id="workflow-id",
            workflow_run_id="run-id",
            workflow_task_list="task-list",
            data_converter=DefaultDataConverter(),
        ),
        workflow_definition=WorkflowDefinition.wrap(
            workflow_class, WorkflowDefinitionOptions(name="workflow")
        ),
        context_propagators=(propagator,),
        headers=headers,
    )
