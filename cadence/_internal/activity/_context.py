import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Callable, Any

from cadence import Client
from cadence._internal.type_utils import get_fn_parameters
from cadence.activity import ActivityInfo, ActivityContext
from cadence.api.v1.common_pb2 import Payload


class _Context(ActivityContext):
    def __init__(self, client: Client, info: ActivityInfo, activity_fn: Callable[[Any], Any]):
        self._client = client
        self._info = info
        self._activity_fn = activity_fn

    async def execute(self, payload: Payload) -> Any:
        params = await self._to_params(payload)
        with self._activate():
            return await self._activity_fn(*params)

    async def _to_params(self, payload: Payload) -> list[Any]:
        type_hints = get_fn_parameters(self._activity_fn)
        return await self._client.data_converter.from_data(payload, type_hints)

    def client(self) -> Client:
        return self._client

    def info(self) -> ActivityInfo:
        return self._info

class _SyncContext(_Context):
    def __init__(self, client: Client, info: ActivityInfo, activity_fn: Callable[[Any], Any], executor: ThreadPoolExecutor):
        super().__init__(client, info, activity_fn)
        self._executor = executor

    async def execute(self, payload: Payload) -> Any:
        params = await self._to_params(payload)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._run, params)

    def _run(self, args: list[Any]) -> Any:
        with self._activate():
            return self._activity_fn(*args)

    def client(self) -> Client:
        raise RuntimeError("client is only supported in async activities")

