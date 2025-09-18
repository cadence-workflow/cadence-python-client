import asyncio
from typing import Optional

from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskRequest, PollForDecisionTaskResponse
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.client import Client
from cadence.worker._poller import Poller
from cadence.worker._types import WorkerOptions, _LONG_POLL_TIMEOUT
from cadence.worker._decision_task_handler import DecisionTaskHandler
from cadence.worker._registry import Registry


class DecisionWorker:
    def __init__(self, client: Client, task_list: str, registry: Registry, options: WorkerOptions) -> None:
        self._client = client
        self._task_list = task_list
        self._registry = registry
        self._identity = options["identity"]
        permits = asyncio.Semaphore(options["max_concurrent_decision_task_execution_size"])
        self._decision_handler = DecisionTaskHandler(client, task_list, registry, **options)
        self._poller = Poller[PollForDecisionTaskResponse](options["decision_task_pollers"], permits, self._poll, self._execute)
        # TODO: Sticky poller, actually running workflows, etc.

    async def run(self) -> None:
        await self._poller.run()

    async def _poll(self) -> Optional[PollForDecisionTaskResponse]:
        task: PollForDecisionTaskResponse = await self._client.worker_stub.PollForDecisionTask(PollForDecisionTaskRequest(
            domain=self._client.domain,
            task_list=TaskList(name=self._task_list,kind=TaskListKind.TASK_LIST_KIND_NORMAL),
            identity=self._identity,
        ), timeout=_LONG_POLL_TIMEOUT)

        if task and task.task_token:
            return task
        else:
            return None


    async def _execute(self, task: PollForDecisionTaskResponse) -> None:
        await self._decision_handler.handle_task(task)

