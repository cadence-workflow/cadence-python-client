import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
from traceback import format_exception
from typing import Any, Callable

from cadence._internal.type_utils import get_fn_parameters
from cadence.api.v1.common_pb2 import Failure
from cadence.api.v1.service_worker_pb2 import PollForActivityTaskResponse, RespondActivityTaskFailedRequest, \
    RespondActivityTaskCompletedRequest
from cadence.client import Client

_logger = getLogger(__name__)

class ActivityExecutor:
    def __init__(self, client: Client, task_list: str, identity: str, max_workers: int, registry: Callable[[str], Callable]):
        self._client = client
        self._data_converter = client.data_converter
        self._registry = registry
        self._identity = identity
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers,
                                               thread_name_prefix=f'{task_list}-activity-')

    async def execute(self, task: PollForActivityTaskResponse):
        activity_type = task.activity_type.name
        try:
            activity_fn = self._registry(activity_type)
        except KeyError as e:
            _logger.error("Activity type not found.", extra={'activity_type': activity_type})
            await self._report_failure(task, e)
            return

        await self._execute_fn(activity_fn, task)

    async def _execute_fn(self, activity_fn: Callable[[Any], Any], task: PollForActivityTaskResponse):
        try:
            type_hints = get_fn_parameters(activity_fn)
            params = await self._client.data_converter.from_data(task.input, type_hints)
            if inspect.iscoroutinefunction(activity_fn):
                result = await activity_fn(*params)
            else:
                result = await self._invoke_sync_activity(activity_fn, params)
            await self._report_success(task, result)
        except Exception as e:
            await self._report_failure(task, e)

    async def _invoke_sync_activity(self, activity_fn: Callable[[Any], Any], params: list[Any]) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._thread_pool, activity_fn, *params)

    async def _report_failure(self, task: PollForActivityTaskResponse, error: Exception):
        try:
            await self._client.worker_stub.RespondActivityTaskFailed(RespondActivityTaskFailedRequest(
                task_token=task.task_token,
                failure=_to_failure(error),
                identity=self._identity,
            ))
        except Exception:
            _logger.exception('Exception reporting activity failure')

    async def _report_success(self, task: PollForActivityTaskResponse, result: Any):
        as_payload = await self._data_converter.to_data(result)

        try:
            await self._client.worker_stub.RespondActivityTaskCompleted(RespondActivityTaskCompletedRequest(
                task_token=task.task_token,
                result=as_payload,
                identity=self._identity,
            ))
        except Exception:
            _logger.exception('Exception reporting activity complete')


def _to_failure(exception: Exception) -> Failure:
    stacktrace = "".join(format_exception(exception))

    return Failure(
        reason=type(exception).__name__,
        details=stacktrace.encode(),
    )
