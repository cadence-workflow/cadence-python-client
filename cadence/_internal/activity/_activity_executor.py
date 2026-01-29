from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
from traceback import format_exception
from typing import Any, Callable, cast
from google.protobuf.duration import to_timedelta
from google.protobuf.timestamp import to_datetime

from cadence._internal.activity._context import _Context, _SyncContext
from cadence._internal.activity._definition import BaseDefinition, ExecutionStrategy
from cadence.activity import ActivityInfo, ActivityDefinition
from cadence.api.v1.common_pb2 import Failure
from cadence.api.v1.service_worker_pb2 import (
    PollForActivityTaskResponse,
    RespondActivityTaskFailedRequest,
    RespondActivityTaskCompletedRequest,
)
from cadence.client import Client

_logger = getLogger(__name__)


class ActivityExecutor:
    def __init__(
        self,
        client: Client,
        task_list: str,
        identity: str,
        max_workers: int,
        registry: Callable[[str], ActivityDefinition],
    ):
        self._client = client
        self._data_converter = client.data_converter
        self._registry = registry
        self._identity = identity
        self._task_list = task_list
        self._thread_pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=f"{task_list}-activity-"
        )

    async def execute(self, task: PollForActivityTaskResponse):
        try:
            context = self._create_context(task)
            result = await context.execute(task.input)
            await self._report_success(task, result)
        except Exception as e:
            _logger.exception("Activity failed")
            await self._report_failure(task, e)

    def _create_context(self, task: PollForActivityTaskResponse) -> _Context:
        activity_type = task.activity_type.name
        try:
            activity_def = cast(BaseDefinition, self._registry(activity_type))
        except KeyError:
            raise KeyError(f"Activity type not found: {activity_type}") from None

        info = self._create_info(task)

        if activity_def.strategy == ExecutionStrategy.ASYNC:
            return _Context(self._client, info, activity_def)
        else:
            return _SyncContext(self._client, info, activity_def, self._thread_pool)

    async def _report_failure(
        self, task: PollForActivityTaskResponse, error: Exception
    ):
        try:
            await self._client.worker_stub.RespondActivityTaskFailed(
                RespondActivityTaskFailedRequest(
                    task_token=task.task_token,
                    failure=_to_failure(error),
                    identity=self._identity,
                )
            )
        except Exception:
            _logger.exception("Exception reporting activity failure")

    async def _report_success(self, task: PollForActivityTaskResponse, result: Any):
        as_payload = self._data_converter.to_data([result])

        try:
            await self._client.worker_stub.RespondActivityTaskCompleted(
                RespondActivityTaskCompletedRequest(
                    task_token=task.task_token,
                    result=as_payload,
                    identity=self._identity,
                )
            )
        except Exception:
            _logger.exception("Exception reporting activity complete")

    def _create_info(self, task: PollForActivityTaskResponse) -> ActivityInfo:
        return ActivityInfo(
            task_token=task.task_token,
            workflow_type=task.workflow_type.name,
            workflow_domain=task.workflow_domain,
            workflow_id=task.workflow_execution.workflow_id,
            workflow_run_id=task.workflow_execution.run_id,
            activity_id=task.activity_id,
            activity_type=task.activity_type.name,
            task_list=self._task_list,
            heartbeat_timeout=to_timedelta(task.heartbeat_timeout),
            scheduled_timestamp=to_datetime(task.scheduled_time),
            started_timestamp=to_datetime(task.started_time),
            start_to_close_timeout=to_timedelta(task.start_to_close_timeout),
            attempt=task.attempt,
        )


def _to_failure(exception: Exception) -> Failure:
    stacktrace = "".join(format_exception(exception))

    return Failure(
        reason=type(exception).__name__,
        details=stacktrace.encode(),
    )
