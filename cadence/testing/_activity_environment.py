"""In-memory test environment for unit testing Cadence activities.

This mirrors the Go client's ``TestActivityEnvironment``
(https://github.com/cadence-workflow/cadence-go-client/blob/master/internal/workflow_testsuite.go),
which runs a single activity synchronously without a Cadence server and returns
its result (or raised error) to the caller.

The user-facing entry point is :class:`TestActivityEnvironment`. Unlike the
production path, nothing here polls gRPC or reports the result back to a server.
The activity is executed through the same :class:`_Context` / :class:`_SyncContext`
used by the real worker, so activity-context APIs behave realistically:

* ``activity.info()`` returns a populated :class:`~cadence.activity.ActivityInfo`.
* ``activity.heartbeat(...)`` details are captured and can be asserted on via
  :meth:`TestActivityEnvironment.get_heartbeat_details`.
* ``activity.heartbeat_details(...)`` returns whatever was seeded with
  :meth:`TestActivityEnvironment.set_heartbeat_details` (simulating a retry).
* Cancellation can be simulated with :meth:`TestActivityEnvironment.cancel`; the
  next heartbeat observes the cancellation request, matching the server behavior
  the async ``asyncio.CancelledError`` / sync ``is_cancelled()`` paths rely on.

Sync activities run on a dedicated thread pool (like the real worker); async
activities run on the calling event loop.
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Type, Union, cast

from cadence._internal.activity._context import _Context, _SyncContext
from cadence._internal.activity._definition import BaseDefinition, ExecutionStrategy
from cadence._internal.activity._heartbeat import _HeartbeatSender
from cadence.activity import ActivityDefinition, ActivityInfo
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.service_worker_pb2 import (
    RecordActivityTaskHeartbeatRequest,
    RecordActivityTaskHeartbeatResponse,
)
from cadence.client import Client
from cadence.data_converter import DataConverter, DefaultDataConverter
from cadence.worker import Registry

_TASK_TOKEN = b"test-task-token"


class _FakeWorkerStub:
    """Stands in for the worker gRPC stub so heartbeats stay in-memory.

    Records every heartbeat's details and reports the environment's simulated
    cancellation state back to the activity via ``cancel_requested``.
    """

    def __init__(self, env: "TestActivityEnvironment") -> None:
        self._env = env

    async def RecordActivityTaskHeartbeat(
        self, request: RecordActivityTaskHeartbeatRequest
    ) -> RecordActivityTaskHeartbeatResponse:
        self._env._record_heartbeat(request.details)
        return RecordActivityTaskHeartbeatResponse(
            cancel_requested=self._env._cancel_requested
        )


class _FakeClient:
    """Minimal ``Client``-compatible object for the activity context.

    Only exposes what :class:`_Context` / :class:`_SyncContext` need. Tests that
    require a fuller client can pass their own via ``client=``.
    """

    def __init__(
        self,
        data_converter: DataConverter,
        worker_stub: _FakeWorkerStub,
        identity: str,
        domain: str,
    ) -> None:
        self._data_converter = data_converter
        self._worker_stub = worker_stub
        self._identity = identity
        self._domain = domain

    @property
    def data_converter(self) -> DataConverter:
        return self._data_converter

    @property
    def worker_stub(self) -> Any:
        return self._worker_stub

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def domain(self) -> str:
        return self._domain


class TestActivityEnvironment:
    """In-memory environment for unit testing a single activity.

    Example::

        env = TestActivityEnvironment()

        @activity.defn
        async def greet(name: str) -> str:
            return f"hello {name}"

        result = await env.execute_activity(greet, "world")
        assert result == "hello world"

    Activities can be passed directly (as returned by ``@activity.defn`` /
    ``@activity.method``) or referenced by name after registering them::

        env = TestActivityEnvironment(registry)
        result = await env.execute_activity("greet", "world")
    """

    # Prevent pytest from collecting this as a test case.
    __test__ = False

    def __init__(
        self,
        registry: Optional[Registry] = None,
        *,
        domain: str = "test-domain",
        task_list: str = "test-task-list",
        identity: str = "test-identity",
        workflow_type: str = "test-workflow-type",
        data_converter: Optional[DataConverter] = None,
        client: Optional[Client] = None,
        heartbeat_timeout: timedelta = timedelta(seconds=60),
        start_to_close_timeout: timedelta = timedelta(seconds=10),
        attempt: int = 1,
    ) -> None:
        self._registry = registry or Registry()
        self._domain = domain
        self._task_list = task_list
        self._identity = identity
        self._workflow_type = workflow_type
        self._heartbeat_timeout = heartbeat_timeout
        self._start_to_close_timeout = start_to_close_timeout
        self._attempt = attempt

        self._data_converter: DataConverter = (
            client.data_converter
            if client is not None
            else (data_converter or DefaultDataConverter())
        )
        self._worker_stub = _FakeWorkerStub(self)
        # Activity code that calls ``activity.client()`` gets the user-provided
        # client when available, otherwise a minimal in-memory stand-in.
        self._client: Client = client if client is not None else cast(
            Client,
            _FakeClient(
                self._data_converter, self._worker_stub, identity, domain
            ),
        )

        # Heartbeat details seeded for the *current* attempt (as if returned by
        # the server from a previous attempt), consumed by heartbeat_details().
        self._seeded_heartbeat_details: Payload = Payload()
        # Details recorded from heartbeats sent during execution.
        self._recorded_heartbeats: list[Payload] = []
        self._cancel_requested = False
        self._test_timeout: Optional[timedelta] = None

        self._thread_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="cadence-test-activity"
        )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def client(self) -> Client:
        """The client returned from ``activity.client()`` during execution."""
        return self._client

    def register_activity(self, defn: ActivityDefinition[Any, Any]) -> None:
        """Register an activity so it can be run by name."""
        self._registry.register_activity(defn)

    def register_activities(self, obj: object) -> None:
        """Register all activity methods found on ``obj`` (e.g. a class instance)."""
        self._registry.register_activities(obj)

    def set_heartbeat_details(self, *details: Any) -> None:
        """Seed the details returned from ``activity.heartbeat_details()``.

        Mirrors Go's ``SetHeartbeatDetails`` and simulates a retry where the
        server hands back the details recorded by a previous attempt.
        """
        self._seeded_heartbeat_details = self._data_converter.to_data(list(details))

    def cancel(self) -> None:
        """Request cancellation of the running activity.

        The request is observed the next time the activity heartbeats (matching
        the real server's ``cancel_requested`` heartbeat response). Async
        activities receive ``asyncio.CancelledError``; sync activities see
        ``activity.is_cancelled()`` return ``True``.
        """
        self._cancel_requested = True

    def set_test_timeout(self, timeout: timedelta) -> "TestActivityEnvironment":
        """Set a wall-clock timeout for :meth:`execute_activity`.

        If the activity does not finish within ``timeout``, execution is
        cancelled and :meth:`execute_activity` raises ``asyncio.TimeoutError``.
        """
        self._test_timeout = timeout
        return self

    @property
    def heartbeat_count(self) -> int:
        """Number of heartbeats recorded during the last execution."""
        return len(self._recorded_heartbeats)

    def get_heartbeat_details(self, *types: Type) -> list[Any]:
        """Decode the details from the most recently recorded heartbeat.

        Pass type hints to decode into specific Python types::

            step, total = env.get_heartbeat_details(int, int)

        Returns an empty list if no heartbeat was recorded.
        """
        if not self._recorded_heartbeats:
            return []
        return self._data_converter.from_data(
            self._recorded_heartbeats[-1], list(types)
        )

    async def execute_activity(
        self,
        activity: Union[str, ActivityDefinition[Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute an activity synchronously and return its result.

        ``activity`` may be an activity definition (as produced by
        ``@activity.defn`` / ``@activity.method``) or the registered name of an
        activity. Arguments are serialized and decoded through the data
        converter, exactly as they would be over the wire, before being passed
        to the activity implementation.

        Any exception raised by the activity propagates to the caller. If
        cancellation was requested (see :meth:`cancel`) and the activity reports
        it, ``asyncio.CancelledError`` or the activity's own exception is raised.
        """
        defn = self._resolve(activity)
        self._recorded_heartbeats = []

        call_args = defn.signature.params_from_call(args, dict(kwargs))
        payload = self._data_converter.to_data(call_args)

        heartbeat_sender = _HeartbeatSender(
            self._worker_stub,  # type: ignore[arg-type]
            self._data_converter,
            _TASK_TOKEN,
            self._identity,
            self._seeded_heartbeat_details,
        )
        info = self._build_info(defn)

        context: Union[_Context, _SyncContext]
        if defn.strategy == ExecutionStrategy.ASYNC:
            context = _Context(self._client, info, defn, heartbeat_sender)
        else:
            context = _SyncContext(
                self._client, info, defn, self._thread_pool, heartbeat_sender
            )

        if self._test_timeout is None:
            return await context.execute(payload)

        # Shield the execution so the timeout surfaces as TimeoutError instead of
        # tripping _Context's "cancelled without request" guard, then cancel the
        # still-running activity ourselves.
        task = asyncio.ensure_future(context.execute(payload))
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), self._test_timeout.total_seconds()
            )
        except (asyncio.TimeoutError, TimeoutError):
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            raise

    def close(self) -> None:
        self._thread_pool.shutdown(wait=False)

    def __enter__(self) -> "TestActivityEnvironment":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(
        self, activity: Union[str, ActivityDefinition[Any, Any]]
    ) -> BaseDefinition:
        if isinstance(activity, BaseDefinition):
            return activity
        if isinstance(activity, str):
            return cast(BaseDefinition, self._registry.get_activity(activity))
        raise TypeError(
            "activity must be an activity definition or a registered activity name, "
            f"got {type(activity)!r}"
        )

    def _record_heartbeat(self, details: Payload) -> None:
        self._recorded_heartbeats.append(details)

    def _build_info(self, defn: BaseDefinition) -> ActivityInfo:
        now = datetime.now(timezone.utc)
        return ActivityInfo(
            task_token=_TASK_TOKEN,
            workflow_type=self._workflow_type,
            workflow_domain=self._domain,
            workflow_id="test-workflow-id",
            workflow_run_id="test-run-id",
            activity_id=str(uuid.uuid4()),
            activity_type=defn.name,
            task_list=self._task_list,
            heartbeat_timeout=self._heartbeat_timeout,
            scheduled_timestamp=now,
            started_timestamp=now,
            start_to_close_timeout=self._start_to_close_timeout,
            attempt=self._attempt,
        )
