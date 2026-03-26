import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from logging import getLogger
from typing import Any

from cadence import Client
from cadence._internal.activity._definition import BaseDefinition
from cadence._internal.activity._heartbeat import _HeartbeatSender
from cadence.activity import ActivityInfo, ActivityContext
from cadence.api.v1.common_pb2 import Payload

_logger = getLogger(__name__)


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

    async def execute(self, payload: Payload) -> Any:
        params = self._to_params(payload)
        with self._activate():
            return await self._activity_def.impl_fn(*params)

    def _to_params(self, payload: Payload) -> list[Any]:
        return self._activity_def.signature.params_from_payload(
            self._client.data_converter, payload
        )

    def client(self) -> Client:
        return self._client

    def info(self) -> ActivityInfo:
        return self._info

    def heartbeat(self, *details: Any) -> None:
        task = asyncio.ensure_future(
            self._heartbeat_sender.send_heartbeat(*details)
        )
        task.add_done_callback(_on_heartbeat_done)


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
        return await self._loop.run_in_executor(self._executor, self._run, params)

    def _run(self, args: list[Any]) -> Any:
        with self._activate():
            return self._activity_def.impl_fn(*args)

    def client(self) -> Client:
        raise RuntimeError("client is only supported in async activities")

    def heartbeat(self, *details: Any) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self._heartbeat_sender.send_heartbeat(*details), self._loop
        )
        future.add_done_callback(_on_heartbeat_done)


def _on_heartbeat_done(task: asyncio.Task | asyncio.Future) -> None:
    exc = task.exception()
    if exc is not None:
        _logger.warning("Heartbeat failed: %s", exc)
