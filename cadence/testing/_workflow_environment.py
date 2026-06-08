"""In-memory test environment for unit testing Cadence workflows.

This mirrors the Go client's ``WorkflowTestSuite`` / ``TestWorkflowEnvironment``
(https://github.com/cadence-workflow/cadence-go-client/blob/master/internal/workflow_testsuite.go).

The user-facing entry point is :class:`TestWorkflowEnvironment`. It hands out a
:class:`MockClient` that implements the public :class:`cadence.client.Client`
interface, so test code can drive workflows exactly like production code does
(``await client.start_workflow(...)``, ``signal_workflow``, ``query_workflow``,
...).

Unlike the production path, nothing here touches gRPC or workflow history. When a
workflow is started, the environment builds a real in-memory
:class:`cadence.workflow.WorkflowContext` (running on the deterministic event
loop) and executes the workflow code directly. Activities are executed inline
(or replaced with mocks), and timers advance a virtual clock instead of waiting
on the wall clock.
"""

from __future__ import annotations

import inspect
import uuid
from asyncio import Future, get_running_loop
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    Callable,
    Optional,
    Tuple,
    Type,
    Union,
    Unpack,
    cast,
)

from cadence._internal.activity._definition import BaseDefinition
from cadence._internal.workflow.deterministic_event_loop import DeterministicEventLoop
from cadence._internal.workflow.workflow_instance import WorkflowInstance
from cadence.activity import ActivityContext, ActivityInfo
from cadence.api.v1.common_pb2 import Payload, WorkflowExecution
from cadence.api.v1.query_pb2 import QueryRejectCondition
from cadence.client import Client, ClientOptions, StartWorkflowOptions
from cadence.data_converter import DataConverter, DefaultDataConverter
from cadence.metrics import NoOpMetricsEmitter
from cadence.workflow import (
    ActivityOptions,
    ChildWorkflowFuture,
    ChildWorkflowOptions,
    ResultType,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowInfo,
)
from cadence.worker import Registry


class _Unset:
    """Sentinel for an unset keyword argument."""


_UNSET: Any = _Unset()


class _ValueMock:
    """Activity mock that returns a fixed value."""

    def __init__(self, value: Any) -> None:
        self.value = value


class _FnMock:
    """Activity mock that delegates to a (sync or async) function."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        self.fn = fn


class _InMemoryActivityContext(ActivityContext):
    """Minimal activity context so real activities can call ``activity.info()``."""

    def __init__(
        self,
        env: "TestWorkflowEnvironment",
        activity_type: str,
        workflow_info: WorkflowInfo,
    ) -> None:
        self._env = env
        self._activity_type = activity_type
        self._workflow_info = workflow_info
        self._heartbeat_details: list[Any] = []

    def info(self) -> ActivityInfo:
        now = self._env.now()
        return ActivityInfo(
            task_token=b"",
            workflow_type=self._workflow_info.workflow_type,
            workflow_domain=self._workflow_info.workflow_domain,
            workflow_id=self._workflow_info.workflow_id,
            workflow_run_id=self._workflow_info.workflow_run_id,
            activity_id=str(uuid.uuid4()),
            activity_type=self._activity_type,
            task_list=self._workflow_info.workflow_task_list,
            heartbeat_timeout=timedelta(0),
            scheduled_timestamp=now,
            started_timestamp=now,
            start_to_close_timeout=timedelta(0),
            attempt=0,
        )

    def client(self) -> Client:
        return self._env.client

    def heartbeat(self, *details: Any) -> None:
        self._heartbeat_details = list(details)

    def heartbeat_details(self, *types: Type) -> list[Any]:
        return list(self._heartbeat_details)


class _InMemoryWorkflowContext(WorkflowContext):
    """A workflow context that runs entirely in memory.

    Activities are executed inline (real implementation or registered mock),
    timers advance the environment's virtual clock, and ``wait_condition`` uses
    the deterministic event loop's predicate waiter just like production.
    """

    def __init__(self, env: "TestWorkflowEnvironment", info: WorkflowInfo) -> None:
        self._env = env
        self._info = info

    def info(self) -> WorkflowInfo:
        return self._info

    def data_converter(self) -> DataConverter:
        return self._info.data_converter

    async def execute_activity(
        self,
        activity: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ActivityOptions],
    ) -> ResultType:
        return await self._env._invoke_activity(
            activity, result_type, args, self._info
        )

    async def execute_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> ResultType:
        future = await self.start_child_workflow(
            workflow_type, result_type, *args, **kwargs
        )
        return await future

    async def start_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> ChildWorkflowFuture[ResultType]:
        return await self._env._start_child_workflow(
            workflow_type, result_type, args, kwargs, self._info
        )

    async def start_timer(self, duration: timedelta) -> None:
        if duration.total_seconds() > 0:
            self._env._advance_clock(duration)
        return None

    async def wait_condition(self, predicate: Callable[[], bool]) -> None:
        loop = cast(DeterministicEventLoop, get_running_loop())
        await loop.create_waiter(predicate)


class _Execution:
    """Holds the in-memory state machine for a single workflow execution."""

    def __init__(
        self,
        env: "TestWorkflowEnvironment",
        workflow_definition: WorkflowDefinition,
        info: WorkflowInfo,
    ) -> None:
        self.info = info
        self._loop = DeterministicEventLoop()
        self._instance = WorkflowInstance(
            self._loop, workflow_definition, info.data_converter
        )
        self._context = _InMemoryWorkflowContext(env, info)
        self.completed: bool = False
        self.result_payload: Optional[Payload] = None
        self.error: Optional[BaseException] = None
        self.cancel_requested: bool = False

    def run_start(
        self,
        payload: Payload,
        pending_signal: Optional[Tuple[str, Payload]] = None,
    ) -> None:
        with self._context._activate():
            self._instance.start(payload)
            if pending_signal is not None:
                name, signal_payload = pending_signal
                self._instance.handle_signal(name, signal_payload)
            self._instance.run_until_yield()
            self._collect_outcome()

    def run_signal(self, name: str, payload: Payload) -> None:
        with self._context._activate():
            self._instance.handle_signal(name, payload)
            self._instance.run_until_yield()
            self._collect_outcome()

    def run_query(self, query_type: str, args: Payload) -> Payload:
        with self._context._activate():
            return self._instance.handle_query(query_type, args)

    def _collect_outcome(self) -> None:
        signal_failure = self._instance.get_signal_failure()
        if signal_failure is not None:
            self.completed = True
            self.error = signal_failure
            return
        if self._instance.is_done():
            self.completed = True
            try:
                self.result_payload = self._instance.get_result()
            except BaseException as exc:  # noqa: BLE001 - surfaced via get_workflow_*
                self.error = exc


class MockClient(Client):
    """A drop-in replacement for :class:`cadence.client.Client`.

    Implements the workflow-execution portion of the ``Client`` interface
    (``start_workflow``, ``signal_workflow``, ``query_workflow``,
    ``cancel_workflow``, ``signal_with_start_workflow``) against an in-memory
    :class:`TestWorkflowEnvironment`. No gRPC channel is created.
    """

    def __init__(self, env: "TestWorkflowEnvironment") -> None:
        # Intentionally do not call super().__init__: there is no gRPC channel.
        self._env = env
        self._channel = None  # type: ignore[assignment]
        self._options = ClientOptions(
            domain=env._domain,
            target="in-memory",
            data_converter=env._data_converter,
            identity="test-workflow-environment",
            metrics_emitter=NoOpMetricsEmitter(),
        )

    async def ready(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def start_workflow(
        self,
        workflow: Union[str, WorkflowDefinition],
        *args: Any,
        **options_kwargs: Unpack[StartWorkflowOptions],
    ) -> WorkflowExecution:
        return await self._env._start_workflow(workflow, args, options_kwargs)

    async def signal_workflow(
        self,
        workflow_id: str,
        run_id: str,
        signal_name: str,
        *signal_args: Any,
    ) -> None:
        await self._env._signal_workflow(workflow_id, signal_name, signal_args)

    async def query_workflow(
        self,
        workflow_id: str,
        run_id: str,
        query_type: str,
        *query_args: Any,
        result_type: type = object,
        query_reject_condition: QueryRejectCondition | None = None,
    ) -> Any:
        return await self._env._query_workflow(
            workflow_id, query_type, query_args, result_type
        )

    async def cancel_workflow(self, workflow_id: str, run_id: str) -> None:
        raise Not

    async def signal_with_start_workflow(
        self,
        workflow: Union[str, WorkflowDefinition],
        signal_name: str,
        signal_args: list[Any],
        *workflow_args: Any,
        **options_kwargs: Unpack[StartWorkflowOptions],
    ) -> WorkflowExecution:
        workflow_id = options_kwargs.get("workflow_id")
        if workflow_id and workflow_id in self._env._executions:
            await self.signal_workflow(workflow_id, "", signal_name, *signal_args)
            execution = self._env._executions[workflow_id]
            return WorkflowExecution(
                workflow_id=workflow_id,
                run_id=execution.info.workflow_run_id,
            )
        return await self._env._start_workflow(
            workflow,
            workflow_args,
            options_kwargs,
            pending_signal=(signal_name, list(signal_args)),
        )


class TestWorkflowEnvironment:
    """In-memory environment for unit testing workflow code.

    Example::

        env = TestWorkflowEnvironment()
        env.register_workflow(GreetingWorkflow)
        env.on_activity("greet", result="hello world")

        client = env.client  # implements the Client interface
        execution = await client.start_workflow(
            "GreetingWorkflow", "world", task_list="tl",
        )
        result = env.get_workflow_result(str)
    """

    # Prevent pytest from collecting this as a test case.
    __test__ = False

    def __init__(
        self,
        registry: Optional[Registry] = None,
        *,
        domain: str = "test-domain",
        task_list: str = "test-task-list",
        data_converter: Optional[DataConverter] = None,
        start_time: Optional[datetime] = None,
    ) -> None:
        self._registry = registry if registry is not None else Registry()
        self._domain = domain
        self._default_task_list = task_list
        self._data_converter = data_converter or DefaultDataConverter()
        self._activity_mocks: dict[str, Union[_ValueMock, _FnMock]] = {}
        self._executions: dict[str, _Execution] = {}
        self._last_execution: Optional[_Execution] = None
        self._now = start_time or datetime.now(timezone.utc)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="cadence-test-env"
        )
        self._client = MockClient(self)

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @property
    def client(self) -> Client:
        """Return the mock client implementing the ``Client`` interface."""
        return self._client

    @property
    def registry(self) -> Registry:
        return self._registry

    def register_workflow(
        self, workflow: Type, *, name: Optional[str] = None
    ) -> Type:
        """Register a workflow class with the environment's registry."""
        if name is not None:
            self._registry.workflow(name=name)(workflow)
        else:
            self._registry.workflow(workflow)
        return workflow

    def register_activity(self, activity: Any) -> None:
        """Register a single activity definition (``@activity.defn``)."""
        self._registry.register_activity(activity)

    def register_activities(self, obj: object) -> None:
        """Register all activity methods found on ``obj``."""
        self._registry.register_activities(obj)

    def on_activity(
        self,
        activity: Union[str, BaseDefinition],
        *,
        result: Any = _UNSET,
        fn: Optional[Callable[..., Any]] = None,
    ) -> "TestWorkflowEnvironment":
        """Mock an activity by name (or definition).

        Provide exactly one of ``result`` (a fixed return value) or ``fn`` (a
        sync/async callable invoked with the decoded activity arguments).
        """
        name = activity if isinstance(activity, str) else activity.name
        if fn is not None:
            self._activity_mocks[name] = _FnMock(fn)
        elif result is not _UNSET:
            self._activity_mocks[name] = _ValueMock(result)
        else:
            raise ValueError("on_activity requires either result= or fn=")
        return self

    def now(self) -> datetime:
        """Return the current workflow (virtual) time."""
        return self._now

    def is_workflow_completed(
        self, workflow_id: str = "", run_id: str = ""
    ) -> bool:
        return self._get_execution(workflow_id).completed

    def get_workflow_result(
        self,
        result_type: type = object,
        workflow_id: str = "",
        run_id: str = "",
    ) -> Any:
        """Return the decoded workflow result.

        Raises the workflow's error if it failed, or ``RuntimeError`` if the
        workflow has not completed.
        """
        execution = self._get_execution(workflow_id)
        if not execution.completed:
            raise RuntimeError("Workflow has not completed")
        if execution.error is not None:
            raise execution.error
        if execution.result_payload is None:
            return None
        return self._data_converter.from_data(
            execution.result_payload, [result_type]
        )[0]

    def get_workflow_error(
        self, workflow_id: str = "", run_id: str = ""
    ) -> Optional[BaseException]:
        return self._get_execution(workflow_id).error

    def close(self) -> None:
        self._executor.shutdown(wait=False)

    def __enter__(self) -> "TestWorkflowEnvironment":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers used by MockClient / contexts
    # ------------------------------------------------------------------

    def _advance_clock(self, duration: timedelta) -> None:
        self._now = self._now + duration

    def _resolve_workflow(
        self, workflow: Union[str, WorkflowDefinition]
    ) -> WorkflowDefinition:
        if isinstance(workflow, WorkflowDefinition):
            return workflow
        if isinstance(workflow, str):
            return self._registry.get_workflow(workflow)
        raise TypeError(
            f"workflow must be a name or WorkflowDefinition, got {type(workflow)!r}"
        )

    def _get_execution(self, workflow_id: str) -> _Execution:
        if not workflow_id:
            if self._last_execution is None:
                raise KeyError("No workflow has been started")
            return self._last_execution
        return self._executions[workflow_id]

    async def _drive(self, fn: Callable[..., Any], *fn_args: Any) -> Any:
        # The deterministic event loop refuses to run while another loop is
        # running, so drive it on a dedicated worker thread (mirroring the
        # production worker, which runs decisions in a thread pool).
        loop = get_running_loop()
        return await loop.run_in_executor(self._executor, fn, *fn_args)

    async def _start_workflow(
        self,
        workflow: Union[str, WorkflowDefinition],
        args: Tuple[Any, ...],
        options: StartWorkflowOptions,
        pending_signal: Optional[Tuple[str, list[Any]]] = None,
    ) -> WorkflowExecution:
        definition = self._resolve_workflow(workflow)
        workflow_id = options.get("workflow_id") or str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        task_list = options.get("task_list") or self._default_task_list

        info = WorkflowInfo(
            workflow_type=definition.name,
            workflow_domain=self._domain,
            workflow_id=workflow_id,
            workflow_run_id=run_id,
            workflow_task_list=task_list,
            data_converter=self._data_converter,
        )
        execution = _Execution(self, definition, info)
        self._executions[workflow_id] = execution
        self._last_execution = execution

        payload = self._data_converter.to_data(list(args))
        signal: Optional[Tuple[str, Payload]] = None
        if pending_signal is not None:
            signal_name, signal_args = pending_signal
            signal = (signal_name, self._data_converter.to_data(list(signal_args)))

        await self._drive(execution.run_start, payload, signal)
        return WorkflowExecution(workflow_id=workflow_id, run_id=run_id)

    async def _signal_workflow(
        self, workflow_id: str, signal_name: str, signal_args: Tuple[Any, ...]
    ) -> None:
        execution = self._get_execution(workflow_id)
        payload = self._data_converter.to_data(list(signal_args))
        await self._drive(execution.run_signal, signal_name, payload)

    async def _query_workflow(
        self,
        workflow_id: str,
        query_type: str,
        query_args: Tuple[Any, ...],
        result_type: type,
    ) -> Any:
        execution = self._get_execution(workflow_id)
        payload = self._data_converter.to_data(list(query_args))
        result_payload = await self._drive(execution.run_query, query_type, payload)
        return self._data_converter.from_data(result_payload, [result_type])[0]

    async def _invoke_activity(
        self,
        activity: str,
        result_type: Type[ResultType],
        args: Tuple[Any, ...],
        info: WorkflowInfo,
    ) -> ResultType:
        name = activity if isinstance(activity, str) else getattr(activity, "name")
        dc = self._data_converter

        mock = self._activity_mocks.get(name)
        definition: Optional[BaseDefinition] = None
        try:
            candidate = self._registry.get_activity(name)
            if isinstance(candidate, BaseDefinition):
                definition = candidate
        except KeyError:
            definition = None

        if mock is None and definition is None:
            raise KeyError(
                f"Activity '{name}' is not registered and has no mock. "
                f"Call env.on_activity('{name}', ...) or register it."
            )

        # Round-trip arguments through the data converter to mimic serialization.
        input_payload = dc.to_data(list(args))
        if definition is not None:
            call_args = definition.signature.params_from_payload(dc, input_payload)
        else:
            call_args = list(args)

        if isinstance(mock, _ValueMock):
            result: Any = mock.value
        elif isinstance(mock, _FnMock):
            result = mock.fn(*call_args)
            if inspect.iscoroutine(result):
                result = await result
        else:
            assert definition is not None
            result = await self._run_real_activity(definition, call_args, name, info)

        result_payload = dc.to_data([result])
        return cast(
            ResultType, dc.from_data(result_payload, [result_type])[0]
        )

    async def _run_real_activity(
        self,
        definition: BaseDefinition,
        call_args: list[Any],
        name: str,
        info: WorkflowInfo,
    ) -> Any:
        activity_ctx = _InMemoryActivityContext(self, name, info)
        with activity_ctx._activate():
            result = definition.impl_fn(*call_args)
            if inspect.iscoroutine(result):
                result = await result
        return result

    async def _start_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        args: Tuple[Any, ...],
        kwargs: ChildWorkflowOptions,
        parent_info: WorkflowInfo,
    ) -> ChildWorkflowFuture[ResultType]:
        definition = self._resolve_workflow(workflow_type)
        child_id = kwargs.get("workflow_id") or (
            f"{parent_info.workflow_id}:child:{uuid.uuid4()}"
        )
        child_run_id = str(uuid.uuid4())
        child_info = WorkflowInfo(
            workflow_type=definition.name,
            workflow_domain=kwargs.get("domain") or parent_info.workflow_domain,
            workflow_id=child_id,
            workflow_run_id=child_run_id,
            workflow_task_list=(
                kwargs.get("task_list") or parent_info.workflow_task_list
            ),
            data_converter=self._data_converter,
        )

        input_payload = self._data_converter.to_data(list(args))
        result_payload = await self._run_workflow_coro(
            definition, child_info, input_payload
        )

        loop = cast(DeterministicEventLoop, get_running_loop())
        result_future: "Future[Payload]" = loop.create_future()
        result_future.set_result(result_payload)
        return ChildWorkflowFuture(
            workflow_id=child_id,
            run_id=child_run_id,
            result_future=result_future,
            result_type=result_type,
            data_converter=self._data_converter,
        )

    async def _run_workflow_coro(
        self,
        definition: WorkflowDefinition,
        info: WorkflowInfo,
        input_payload: Payload,
    ) -> Payload:
        instance = definition.cls()
        run_method = definition.get_run_method(instance)
        # noinspection PyProtectedMember
        run_args = definition._run_signature.params_from_payload(
            self._data_converter, input_payload
        )
        child_ctx = _InMemoryWorkflowContext(self, info)
        token = WorkflowContext._var.set(child_ctx)
        try:
            result = await run_method(*run_args)
        finally:
            WorkflowContext._var.reset(token)
        return self._data_converter.to_data([result])
