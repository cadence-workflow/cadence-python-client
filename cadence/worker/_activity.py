import asyncio
from typing import Optional

from cadence.api.v1.common_pb2 import Failure
from cadence.api.v1.service_worker_pb2 import PollForActivityTaskResponse, PollForActivityTaskRequest, \
    RespondActivityTaskFailedRequest
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.client import Client
from cadence.worker._types import WorkerOptions, _LONG_POLL_TIMEOUT
from cadence.worker._poller import Poller


class ActivityWorker:
    def __init__(self, client: Client, task_list: str, options: WorkerOptions) -> None:
        self._client = client
        self._task_list = task_list
        self._identity = options["identity"]
        permits = asyncio.Semaphore(options["max_concurrent_activity_execution_size"])
        self._poller = Poller[PollForActivityTaskResponse](options["activity_task_pollers"], permits, self._poll, self._execute)
        # TODO: Local dispatch, local activities, actually running activities, etc

    async def run(self) -> None:
        await self._poller.run()

    async def _poll(self) -> Optional[PollForActivityTaskResponse]:
        task: PollForActivityTaskResponse = await self._client.worker_stub.PollForActivityTask(PollForActivityTaskRequest(
            domain=self._client.domain,
            task_list=TaskList(name=self._task_list,kind=TaskListKind.TASK_LIST_KIND_NORMAL),
            identity=self._identity,
        ), timeout=_LONG_POLL_TIMEOUT)

        if task.task_token:
            return task
        else:
            return None

    async def _execute(self, task: PollForActivityTaskResponse) -> None:
        await self._client.worker_stub.RespondActivityTaskFailed(RespondActivityTaskFailedRequest(
            task_token=task.task_token,
            identity=self._identity,
            failure=Failure(reason='error', details=b'not implemented'),
        ))

