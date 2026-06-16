import asyncio
import time
from typing import Optional

from cadence._internal.activity import ActivityExecutor
from cadence._internal.rpc.retry import RETRYABLE_CODES
from cadence.api.v1.service_worker_pb2 import (
    PollForActivityTaskResponse,
    PollForActivityTaskRequest,
)
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.client import Client
from cadence.error import CadenceRpcError
from cadence.metrics import MetricsEmitter, NoOpMetricsEmitter
from cadence.metrics.constants import (
    ACTIVITY_POLL_COUNTER,
    ACTIVITY_POLL_FAILED_COUNTER,
    ACTIVITY_POLL_LATENCY,
    ACTIVITY_POLL_NO_TASK_COUNTER,
    ACTIVITY_POLL_SUCCEED_COUNTER,
    ACTIVITY_POLL_TRANSIENT_FAILED_COUNTER,
    ACTIVITY_SCHEDULED_TO_START_LATENCY,
    POLLER_START_COUNTER,
    TAG_DOMAIN,
    TAG_TASK_LIST,
    WORKER_PANIC_COUNTER,
    WORKER_START_COUNTER,
)
from cadence.worker._registry import Registry
from cadence.worker._types import WorkerOptions, _LONG_POLL_TIMEOUT
from cadence.worker._poller import Poller


class ActivityWorker:
    def __init__(
        self, client: Client, task_list: str, registry: Registry, options: WorkerOptions
    ) -> None:
        self._client = client
        self._task_list = task_list
        self._identity = options["identity"]
        self._metrics_emitter: MetricsEmitter = options.get(  # type: ignore[attr-defined]
            "metrics_emitter", NoOpMetricsEmitter()
        )
        self._tags = {TAG_DOMAIN: client.domain, TAG_TASK_LIST: task_list}
        self._num_pollers = options["activity_task_pollers"]
        max_concurrent = options["max_concurrent_activity_execution_size"]
        permits = asyncio.Semaphore(max_concurrent)
        self._executor = ActivityExecutor(
            self._client,
            self._task_list,
            options["identity"],
            max_concurrent,
            registry.get_activity,
            options["metrics_emitter"],
        )
        self._poller = Poller[PollForActivityTaskResponse](
            self._num_pollers, permits, self._poll, self._execute
        )
        # TODO: Local dispatch, local activities, actually running activities, etc

    async def run(self) -> None:
        self._metrics_emitter.counter(WORKER_START_COUNTER, tags=self._tags)
        self._metrics_emitter.counter(POLLER_START_COUNTER, self._num_pollers, tags=self._tags)
        try:
            await self._poller.run()
        except Exception:
            self._metrics_emitter.counter(WORKER_PANIC_COUNTER, tags=self._tags)
            raise

    async def _poll(self) -> Optional[PollForActivityTaskResponse]:
        self._metrics_emitter.counter(ACTIVITY_POLL_COUNTER, tags=self._tags)
        start = time.monotonic()
        try:
            task: PollForActivityTaskResponse = (
                await self._client.worker_stub.PollForActivityTask(
                    PollForActivityTaskRequest(
                        domain=self._client.domain,
                        task_list=TaskList(
                            name=self._task_list, kind=TaskListKind.TASK_LIST_KIND_NORMAL
                        ),
                        identity=self._identity,
                    ),
                    timeout=_LONG_POLL_TIMEOUT,
                )
            )
        except CadenceRpcError as e:
            elapsed = time.monotonic() - start
            self._metrics_emitter.histogram(ACTIVITY_POLL_LATENCY, elapsed, tags=self._tags)
            if e.code in RETRYABLE_CODES:
                self._metrics_emitter.counter(
                    ACTIVITY_POLL_TRANSIENT_FAILED_COUNTER, tags=self._tags
                )
            else:
                self._metrics_emitter.counter(ACTIVITY_POLL_FAILED_COUNTER, tags=self._tags)
            raise

        elapsed = time.monotonic() - start
        self._metrics_emitter.histogram(ACTIVITY_POLL_LATENCY, elapsed, tags=self._tags)

        if task.task_token:
            self._metrics_emitter.counter(ACTIVITY_POLL_SUCCEED_COUNTER, tags=self._tags)
            if task.scheduled_time.seconds and task.started_time.seconds:
                scheduled_to_start = (
                    task.started_time.seconds + task.started_time.nanos / 1e9
                ) - (task.scheduled_time.seconds + task.scheduled_time.nanos / 1e9)
                self._metrics_emitter.histogram(
                    ACTIVITY_SCHEDULED_TO_START_LATENCY, scheduled_to_start, tags=self._tags
                )
            return task
        else:
            self._metrics_emitter.counter(ACTIVITY_POLL_NO_TASK_COUNTER, tags=self._tags)
            return None

    async def _execute(self, task: PollForActivityTaskResponse) -> None:
        await self._executor.execute(task)
