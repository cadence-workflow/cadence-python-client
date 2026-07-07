from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
import time
from traceback import format_exception
from typing import Any, Callable, Optional, Union, cast
from google.protobuf.duration import to_timedelta
from google.protobuf.timestamp import to_datetime

from cadence._internal.activity._context import _Context, _SyncContext
from cadence._internal.activity._definition import BaseDefinition, ExecutionStrategy
from cadence._internal.activity._heartbeat import _HeartbeatSender
from cadence.activity import ActivityInfo, ActivityDefinition
from cadence.api.v1.common_pb2 import Failure
from cadence.api.v1.service_worker_pb2 import (
    PollForActivityTaskResponse,
    RespondActivityTaskFailedRequest,
    RespondActivityTaskCompletedRequest,
)
from cadence.client import Client
from cadence.metrics import MetricsEmitter, NoOpMetricsEmitter
from cadence.metrics.constants import (
    ACTIVITY_END_TO_END_LATENCY,
    ACTIVITY_EXECUTION_FAILED_COUNTER,
    ACTIVITY_EXECUTION_LATENCY,
    ACTIVITY_RESPONSE_FAILED_COUNTER,
    ACTIVITY_RESPONSE_LATENCY,
    ACTIVITY_TASK_COMPLETED_COUNTER,
    ACTIVITY_TASK_FAILED_COUNTER,
    TAG_ACTIVITY_TYPE,
    TAG_DOMAIN,
    TAG_TASK_LIST,
    TAG_WORKFLOW_TYPE,
)

_logger = getLogger(__name__)


class ActivityExecutor:
    def __init__(
        self,
        client: Client,
        task_list: str,
        identity: str,
        max_workers: int,
        registry: Callable[[str], ActivityDefinition],
        metrics_emitter: MetricsEmitter | None = None,
    ):
        self._client = client
        self._data_converter = client.data_converter
        self._registry = registry
        self._identity = identity
        self._task_list = task_list
        self._metrics_emitter: MetricsEmitter = (
            metrics_emitter if metrics_emitter is not None else NoOpMetricsEmitter()
        )
        self._thread_pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=f"{task_list}-activity-"
        )

    async def execute(self, task: PollForActivityTaskResponse):
        activity_type = task.activity_type.name if task.activity_type else "unknown"
        wf_type = task.workflow_type.name if task.workflow_type else "unknown"
        emitter = self._metrics_emitter.with_tags(
            {
                TAG_ACTIVITY_TYPE: activity_type,
                TAG_WORKFLOW_TYPE: wf_type,
                TAG_DOMAIN: self._client.domain,
                TAG_TASK_LIST: self._task_list,
            }
        )
        scheduled_ts = task.scheduled_time.seconds + task.scheduled_time.nanos / 1e9

        error: Optional[Exception] = None
        result: Any = None
        exec_start = time.monotonic()
        try:
            context = self._create_context(task)
            result = await context.execute(task.input)
        except Exception as e:
            error = e
        finally:
            emitter.histogram(
                ACTIVITY_EXECUTION_LATENCY, (time.monotonic() - exec_start) * 1e9
            )

        e2e = time.time() - scheduled_ts if scheduled_ts else None
        if error is not None:
            emitter.counter(ACTIVITY_EXECUTION_FAILED_COUNTER)
            _logger.error("Activity failed", exc_info=error)
            await self._report_failure(task, error, emitter, e2e)
        else:
            await self._report_success(task, result, emitter, e2e)

    def _create_context(
        self, task: PollForActivityTaskResponse
    ) -> Union[_Context, _SyncContext]:
        activity_type = task.activity_type.name
        try:
            activity_def = cast(BaseDefinition, self._registry(activity_type))
        except KeyError:
            raise KeyError(f"Activity type not found: {activity_type}") from None

        info = self._create_info(task)
        heartbeat_sender = _HeartbeatSender(
            self._client.worker_stub,
            self._data_converter,
            task.task_token,
            self._identity,
            task.heartbeat_details,
        )

        if activity_def.strategy == ExecutionStrategy.ASYNC:
            return _Context(self._client, info, activity_def, heartbeat_sender)
        else:
            return _SyncContext(
                self._client,
                info,
                activity_def,
                self._thread_pool,
                heartbeat_sender,
            )

    async def _report_failure(
        self,
        task: PollForActivityTaskResponse,
        error: Exception,
        emitter: Optional[MetricsEmitter] = None,
        e2e_latency: Optional[float] = None,
    ):
        emitter = emitter if emitter is not None else self._metrics_emitter
        resp_start = time.monotonic()
        try:
            await self._client.worker_stub.RespondActivityTaskFailed(
                RespondActivityTaskFailedRequest(
                    task_token=task.task_token,
                    failure=_to_failure(error),
                    identity=self._identity,
                )
            )
            emitter.counter(ACTIVITY_TASK_FAILED_COUNTER)
            if e2e_latency is not None:
                emitter.histogram(
                    ACTIVITY_END_TO_END_LATENCY, max(0.0, e2e_latency) * 1e9
                )
        except Exception:
            emitter.counter(ACTIVITY_RESPONSE_FAILED_COUNTER)
            _logger.exception("Exception reporting activity failure")
        finally:
            emitter.histogram(
                ACTIVITY_RESPONSE_LATENCY, (time.monotonic() - resp_start) * 1e9
            )

    async def _report_success(
        self,
        task: PollForActivityTaskResponse,
        result: Any,
        emitter: Optional[MetricsEmitter] = None,
        e2e_latency: Optional[float] = None,
    ):
        emitter = emitter if emitter is not None else self._metrics_emitter
        as_payload = self._data_converter.to_data([result])
        resp_start = time.monotonic()
        try:
            await self._client.worker_stub.RespondActivityTaskCompleted(
                RespondActivityTaskCompletedRequest(
                    task_token=task.task_token,
                    result=as_payload,
                    identity=self._identity,
                )
            )
            emitter.counter(ACTIVITY_TASK_COMPLETED_COUNTER)
            if e2e_latency is not None:
                emitter.histogram(
                    ACTIVITY_END_TO_END_LATENCY, max(0.0, e2e_latency) * 1e9
                )
        except Exception:
            emitter.counter(ACTIVITY_RESPONSE_FAILED_COUNTER)
            _logger.exception("Exception reporting activity complete")
        finally:
            emitter.histogram(
                ACTIVITY_RESPONSE_LATENCY, (time.monotonic() - resp_start) * 1e9
            )

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
