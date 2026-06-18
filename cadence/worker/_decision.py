import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from cadence.api.v1.service_worker_pb2 import (
    PollForDecisionTaskRequest,
    PollForDecisionTaskResponse,
)
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.client import Client
from cadence.error import CadenceRpcError
from cadence.metrics import MetricsEmitter
from cadence.metrics.constants import (
    DECISION_POLL_COUNTER,
    DECISION_POLL_FAILED_COUNTER,
    DECISION_POLL_LATENCY,
    DECISION_POLL_NO_TASK_COUNTER,
    DECISION_POLL_SUCCEED_COUNTER,
    DECISION_POLL_TRANSIENT_FAILED_COUNTER,
    DECISION_SCHEDULED_TO_START_LATENCY,
    TAG_DOMAIN,
    TAG_TASK_LIST,
)
from cadence.worker._decision_task_handler import DecisionTaskHandler
from cadence.worker._poll_metrics import PollMetrics, run_with_lifecycle_metrics
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
        self._tags = {TAG_DOMAIN: client.domain, TAG_TASK_LIST: task_list}
        self._num_pollers = options["decision_task_pollers"]
        self._poll_metrics = PollMetrics(
            emitter=self._metrics_emitter,
            tags=self._tags,
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
            self._num_pollers, permits, self._poll, self._execute
        )
        # TODO: Sticky poller, actually running workflows, etc.

    async def run(self) -> None:
        await run_with_lifecycle_metrics(
            self._metrics_emitter,
            self._poller,
            num_pollers=self._num_pollers,
            tags=self._tags,
        )

    async def _poll(self) -> Optional[PollForDecisionTaskResponse]:
        start = self._poll_metrics.start_poll()
        try:
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
        except CadenceRpcError as e:
            self._poll_metrics.record_failure(start, e)
            raise
        self._poll_metrics.record_result(start, task)
        return task if (task and task.task_token) else None

    async def _execute(self, task: PollForDecisionTaskResponse) -> None:
        await self._decision_handler.handle_task(task)
