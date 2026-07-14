import asyncio
from typing import Optional

from cadence._internal.activity import ActivityExecutor
from cadence.api.v1.service_worker_pb2 import (
    PollForActivityTaskResponse,
    PollForActivityTaskRequest,
)
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.client import Client
from cadence.metrics import MetricsEmitter
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
from cadence.worker._poll_metrics import PollMetrics
from cadence.worker._poller import Poller
from cadence.worker._registry import Registry
from cadence.worker._types import WorkerOptions, _LONG_POLL_TIMEOUT


class ActivityWorker:
    def __init__(
        self, client: Client, task_list: str, registry: Registry, options: WorkerOptions
    ) -> None:
        self._client = client
        self._task_list = task_list
        self._identity = options["identity"]
        self._metrics_emitter: MetricsEmitter = options["metrics_emitter"]
        self._tagged_emitter = self._metrics_emitter.with_tags(
            {TAG_DOMAIN: client.domain, TAG_TASK_LIST: task_list}
        )
        self._num_pollers = options["activity_task_pollers"]
        self._poll_metrics = PollMetrics(
            emitter=self._tagged_emitter,
            poll=ACTIVITY_POLL_COUNTER,
            latency=ACTIVITY_POLL_LATENCY,
            succeed=ACTIVITY_POLL_SUCCEED_COUNTER,
            no_task=ACTIVITY_POLL_NO_TASK_COUNTER,
            failed=ACTIVITY_POLL_FAILED_COUNTER,
            transient_failed=ACTIVITY_POLL_TRANSIENT_FAILED_COUNTER,
            scheduled_to_start=ACTIVITY_SCHEDULED_TO_START_LATENCY,
        )
        max_concurrent = options["max_concurrent_activity_execution_size"]
        permits = asyncio.Semaphore(max_concurrent)
        self._executor = ActivityExecutor(
            self._client,
            self._task_list,
            options["identity"],
            max_concurrent,
            registry.get_activity,
            options["metrics_emitter"],
            options.get("context_propagators") or (),
        )
        self._poller = Poller[PollForActivityTaskResponse](
            self._num_pollers,
            permits,
            self._poll,
            self._execute,
            on_start=lambda num_pollers: self._tagged_emitter.counter(
                POLLER_START_COUNTER, num_pollers
            ),
        )
        # TODO: Local dispatch, local activities, actually running activities, etc

    async def run(self) -> None:
        self._tagged_emitter.counter(WORKER_START_COUNTER)
        try:
            await self._poller.run()
        except Exception:
            self._tagged_emitter.counter(WORKER_PANIC_COUNTER)
            raise

    async def _poll(self) -> Optional[PollForActivityTaskResponse]:
        async with self._poll_metrics.track():
            task: PollForActivityTaskResponse = (
                await self._client.worker_stub.PollForActivityTask(
                    PollForActivityTaskRequest(
                        domain=self._client.domain,
                        task_list=TaskList(
                            name=self._task_list,
                            kind=TaskListKind.TASK_LIST_KIND_NORMAL,
                        ),
                        identity=self._identity,
                    ),
                    timeout=_LONG_POLL_TIMEOUT.total_seconds(),
                )
            )
            self._poll_metrics.record_result(task)
            return task if task.task_token else None

    async def _execute(self, task: PollForActivityTaskResponse) -> None:
        await self._executor.execute(task)
