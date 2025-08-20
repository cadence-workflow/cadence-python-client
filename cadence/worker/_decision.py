import asyncio
from typing import Optional

from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskRequest, PollForDecisionTaskResponse, \
    RespondDecisionTaskFailedRequest
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.api.v1.workflow_pb2 import DecisionTaskFailedCause
from cadence.client import Client
from cadence.worker._poller import Poller
from cadence.worker._types import WorkerOptions, _LONG_POLL_TIMEOUT


class DecisionWorker:
    def __init__(self, client: Client, task_list: str, options: WorkerOptions):
        self._client = client
        self._task_list = task_list
        self._identity = options["identity"]
        permits = asyncio.Semaphore(options["max_concurrent_decision_task_execution_size"])
        self._poller = Poller[PollForDecisionTaskResponse](options["decision_task_pollers"], permits, self._poll, self._execute)
        # TODO: Sticky poller, actually running workflows, etc.

    async def run(self):
        await self._poller.run()

    async def _poll(self) -> Optional[PollForDecisionTaskResponse]:
        task: PollForDecisionTaskResponse = await self._client.worker_stub.PollForDecisionTask(PollForDecisionTaskRequest(
            domain=self._client.domain,
            task_list=TaskList(name=self._task_list,kind=TaskListKind.TASK_LIST_KIND_NORMAL),
            identity=self._identity,
        ), timeout=_LONG_POLL_TIMEOUT)

        if task.task_token:
            return task
        else:
            return None


    async def _execute(self, task: PollForDecisionTaskResponse):
        await self._client.worker_stub.RespondDecisionTaskFailed(RespondDecisionTaskFailedRequest(
            task_token=task.task_token,
            cause=DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_UNHANDLED_DECISION,
            identity=self._identity,
            details=Payload(data=b'not implemented')
        ))

