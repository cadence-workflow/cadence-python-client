import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Any, Type

from cadence import Client
from cadence._internal.activity._definition import BaseDefinition
from cadence._internal.activity._heartbeat import _HeartbeatSender
from cadence.activity import ActivityInfo, ActivityContext
from cadence.api.v1.common_pb2 import Payload


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
        self._heartbeat_tasks: set[asyncio.Future[None]] = set()

    async def execute(self, payload: Payload) -> Any:
        params = self._to_params(payload)
        try:
            with self._activate():
                return await self._activity_def.impl_fn(*params)
        finally:
            await self._wait_pending_heartbeats()

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
        heartbeat_task.add_done_callback(self._heartbeat_tasks.discard)

    def heartbeat_details(self, *types: Type) -> list[Any]:
        return self._heartbeat_sender.get_details(*types)


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
        future = asyncio.run_coroutine_threadsafe(
            self._heartbeat_sender.send_heartbeat(*details), self._loop
        )
        wrapped = asyncio.wrap_future(future, loop=self._loop)
        self._heartbeat_tasks.add(wrapped)
        wrapped.add_done_callback(self._heartbeat_tasks.discard)
