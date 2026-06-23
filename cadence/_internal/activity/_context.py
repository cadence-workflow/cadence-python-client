import asyncio
import threading
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, Type

from cadence import Client
from cadence._internal.activity._definition import BaseDefinition
from cadence._internal.activity._heartbeat import _HeartbeatSender
from cadence.activity import ActivityInfo, ActivityContext
from cadence.api.v1.common_pb2 import Payload
from cadence.error import ActivityCancelledError


class _Context(ActivityContext):
    def __init__(
        self,
        client: Client,
        info: ActivityInfo,
        activity_def: BaseDefinition[[Any], Any],
        heartbeat_sender: _HeartbeatSender,
    ):
        self._client = client
        self._info = info
        self._activity_def = activity_def
        self._heartbeat_sender = heartbeat_sender
        self._activity_task: asyncio.Task[Any] | None = None
        self._heartbeat_tasks: set[asyncio.Future[Any]] = set()
        self._cancel_event = asyncio.Event()

    async def execute(self, payload: Payload) -> Any:
        params = self._to_params(payload)
        self._activity_task = asyncio.create_task(self._run_activity(params))
        try:
            return await self._activity_task
        except asyncio.CancelledError as e:
            if self.is_cancelled():
                raise ActivityCancelledError()
            raise RuntimeError(
                "Activity raised asyncio.CancelledError without cancellation being "
                "requested"
            ) from e
        finally:
            await self._wait_pending_heartbeats()

    async def _run_activity(self, params: list[Any]) -> Any:
        with self._activate():
            return await self._activity_def.impl_fn(*params)

    async def _wait_pending_heartbeats(self) -> None:
        if not self._heartbeat_tasks:
            return
        tasks = list(self._heartbeat_tasks)
        await asyncio.gather(*tasks, return_exceptions=True)

    def _to_params(self, payload: Payload) -> list[Any]:
        return self._activity_def.signature.params_from_payload(
            self._client.data_converter, payload
        )

    def client(self) -> Client:
        return self._client

    def info(self) -> ActivityInfo:
        return self._info

    def heartbeat(self, *details: Any) -> None:
        heartbeat_task = asyncio.create_task(
            self._heartbeat_sender.send_heartbeat(*details)
        )
        self._heartbeat_tasks.add(heartbeat_task)
        heartbeat_task.add_done_callback(self._cancel_if_requested)
        heartbeat_task.add_done_callback(self._heartbeat_tasks.discard)

    def _cancel_if_requested(self, future: asyncio.Future[bool]) -> None:
        try:
            if future.result() and self._activity_task is not None:
                self._cancel_event.set()
                self._activity_task.cancel()
        except Exception:
            # Heartbeat failure is already logged in _HeartbeatSender.send_heartbeat.
            pass

    def heartbeat_details(self, *types: Type) -> list[Any]:
        return self._heartbeat_sender.get_details(*types)

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def wait_for_cancelled(self, timeout: timedelta | float | None = None) -> bool:
        raise RuntimeError(
            "wait_for_cancelled is only supported in sync activities; "
            "handle asyncio.CancelledError in async activities instead"
        )


class _SyncContext(_Context):
    def __init__(
        self,
        client: Client,
        info: ActivityInfo,
        activity_def: BaseDefinition[[Any], Any],
        executor: ThreadPoolExecutor,
        heartbeat_sender: _HeartbeatSender,
    ):
        super().__init__(client, info, activity_def, heartbeat_sender)
        self._executor = executor
        self._sync_cancel_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def is_cancelled(self) -> bool:
        return self._sync_cancel_event.is_set()

    async def execute(self, payload: Payload) -> Any:
        params = self._to_params(payload)
        self._loop = asyncio.get_running_loop()
        try:
            return await self._loop.run_in_executor(self._executor, self._run, params)
        finally:
            await self._wait_pending_heartbeats()

    def _run(self, args: list[Any]) -> Any:
        with self._activate():
            return self._activity_def.impl_fn(*args)

    def client(self) -> Client:
        raise RuntimeError("client is only supported in async activities")

    def heartbeat(self, *details: Any) -> None:
        if self._loop is None:
            raise RuntimeError("heartbeat() called before activity execution started")
        future: ConcurrentFuture[bool] = asyncio.run_coroutine_threadsafe(
            self._heartbeat_sender.send_heartbeat(*details), self._loop
        )
        future.add_done_callback(self._sync_cancel_if_requested)
        wrapped = asyncio.wrap_future(future, loop=self._loop)
        self._heartbeat_tasks.add(wrapped)
        wrapped.add_done_callback(self._heartbeat_tasks.discard)

    def _sync_cancel_if_requested(self, future: ConcurrentFuture[bool]) -> None:
        try:
            if future.result():
                self._sync_cancel_event.set()
        except Exception:
            pass

    def wait_for_cancelled(self, timeout: timedelta | float | None = None) -> bool:
        if timeout is None:
            sec: float | None = None
        elif isinstance(timeout, timedelta):
            sec = timeout.total_seconds()
        else:
            sec = float(timeout)
        return self._sync_cancel_event.wait(sec)
