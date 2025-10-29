import asyncio
from typing import Optional

from cadence._internal.activity import ActivityExecutor
from cadence.api.v1.service_worker_pb2 import (
    PollForActivityTaskResponse,
    PollForActivityTaskRequest,
)
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.client import Client
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
        max_concurrent = options["max_concurrent_activity_execution_size"]
        permits = asyncio.Semaphore(max_concurrent)
        self._executor = ActivityExecutor(
            self._client,
            self._task_list,
            options["identity"],
            max_concurrent,
            registry.get_activity,
        )
        self._poller = Poller[PollForActivityTaskResponse](
            options["activity_task_pollers"], permits, self._poll, self._execute
        )
        # TODO: Local dispatch, local activities, actually running activities, etc

    async def run(self) -> None:
        await self._poller.run()

    async def _poll(self) -> Optional[PollForActivityTaskResponse]:
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

        if task.task_token:
            return task
        else:
            return None

    async def _execute(self, task: PollForActivityTaskResponse) -> None:
        await self._executor.execute(task)
