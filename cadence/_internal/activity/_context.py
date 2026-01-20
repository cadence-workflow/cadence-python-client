import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Any

from cadence import Client
from cadence._internal.activity._definition import BaseDefinition
from cadence.activity import ActivityInfo, ActivityContext
from cadence.api.v1.common_pb2 import Payload


class _Context(ActivityContext):
    def __init__(
        self,
        client: Client,
        info: ActivityInfo,
        activity_def: BaseDefinition[[Any], Any],
    ):
        self._client = client
        self._info = info
        self._activity_def = activity_def

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


class _SyncContext(_Context):
    def __init__(
        self,
        client: Client,
        info: ActivityInfo,
        activity_def: BaseDefinition[[Any], Any],
        executor: ThreadPoolExecutor,
    ):
        super().__init__(client, info, activity_def)
        self._executor = executor

    async def execute(self, payload: Payload) -> Any:
        params = self._to_params(payload)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._run, params)

    def _run(self, args: list[Any]) -> Any:
        with self._activate():
            return self._activity_def.impl_fn(*args)

    def client(self) -> Client:
        raise RuntimeError("client is only supported in async activities")
