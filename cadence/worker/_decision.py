import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from cadence.api.v1.service_worker_pb2 import (
    PollForDecisionTaskRequest,
    PollForDecisionTaskResponse,
)
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.client import Client
from cadence.metrics import MetricsEmitter
from cadence.metrics.constants import (
    DECISION_POLL_COUNTER,
    DECISION_POLL_FAILED_COUNTER,
    DECISION_POLL_LATENCY,
    DECISION_POLL_NO_TASK_COUNTER,
    DECISION_POLL_SUCCEED_COUNTER,
    DECISION_POLL_TRANSIENT_FAILED_COUNTER,
    DECISION_SCHEDULED_TO_START_LATENCY,
    POLLER_START_COUNTER,
    TAG_DOMAIN,
    TAG_TASK_LIST,
    WORKER_PANIC_COUNTER,
    WORKER_START_COUNTER,
)
from cadence.worker._decision_task_handler import DecisionTaskHandler
from cadence.worker._poll_metrics import PollMetrics
from cadence.worker._poller import Poller
from cadence.worker._registry import Registry
from cadence.worker._types import _LONG_POLL_TIMEOUT, WorkerOptions


class DecisionWorker:
    def __init__(
        self, client: Client, task_list: str, registry: Registry, options: WorkerOptions
    ) -> None:
        self._client = client
        self._task_list = task_list
        self._registry = registry
        self._identity = options["identity"]
        self._metrics_emitter: MetricsEmitter = options["metrics_emitter"]
        self._tagged_emitter = self._metrics_emitter.with_tags(
            {TAG_DOMAIN: client.domain, TAG_TASK_LIST: task_list}
        )
        self._num_pollers = options["decision_task_pollers"]
        self._poll_metrics = PollMetrics(
            emitter=self._tagged_emitter,
            poll=DECISION_POLL_COUNTER,
            latency=DECISION_POLL_LATENCY,
            succeed=DECISION_POLL_SUCCEED_COUNTER,
            no_task=DECISION_POLL_NO_TASK_COUNTER,
            failed=DECISION_POLL_FAILED_COUNTER,
            transient_failed=DECISION_POLL_TRANSIENT_FAILED_COUNTER,
            scheduled_to_start=DECISION_SCHEDULED_TO_START_LATENCY,
        )
        permits = asyncio.Semaphore(
            options["max_concurrent_decision_task_execution_size"]
        )
        executor = ThreadPoolExecutor(
            max_workers=options["max_concurrent_decision_task_execution_size"]
        )
        self._decision_handler = DecisionTaskHandler(
            client, task_list, registry, executor=executor, **options
        )
        self._poller = Poller[PollForDecisionTaskResponse](
            self._num_pollers,
            permits,
            self._poll,
            self._execute,
            on_start=lambda num_pollers: self._tagged_emitter.counter(
                POLLER_START_COUNTER, num_pollers
            ),
        )
        # TODO: Sticky poller, actually running workflows, etc.

    async def run(self) -> None:
        self._tagged_emitter.counter(WORKER_START_COUNTER)
        try:
            await self._poller.run()
        except Exception:
            self._tagged_emitter.counter(WORKER_PANIC_COUNTER)
            raise

    async def _poll(self) -> Optional[PollForDecisionTaskResponse]:
        async with self._poll_metrics.track():
            task: PollForDecisionTaskResponse = (
                await self._client.worker_stub.PollForDecisionTask(
                    PollForDecisionTaskRequest(
                        domain=self._client.domain,
                        task_list=TaskList(
                            name=self._task_list,
                            kind=TaskListKind.TASK_LIST_KIND_NORMAL,
                        ),
                        identity=self._identity,
                    ),
                    timeout=_LONG_POLL_TIMEOUT,
                )
            )
            self._poll_metrics.record_result(task)
            return task if (task and task.task_token) else None

    async def _execute(self, task: PollForDecisionTaskResponse) -> None:
        await self._decision_handler.handle_task(task)
