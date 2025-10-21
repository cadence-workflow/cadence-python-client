import asyncio

import pytest

from unittest.mock import AsyncMock, Mock, PropertyMock

from cadence.api.v1.service_worker_pb2 import (
    PollForDecisionTaskRequest,
    PollForActivityTaskRequest,
)
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.client import Client
from cadence.worker import Worker, Registry


@pytest.mark.asyncio
async def test_worker():
    client = Mock(spec=Client)
    done = asyncio.Event()
    both_waited = asyncio.Barrier(3)

    async def poll(_, timeout=0.0):
        await both_waited.wait()
        await done.wait()
        return None

    worker_stub = Mock()
    worker_stub.PollForDecisionTask = AsyncMock(side_effect=poll)
    worker_stub.PollForActivityTask = AsyncMock(side_effect=poll)

    client.worker_stub = worker_stub
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")

    worker = Worker(
        client,
        "task_list",
        Registry(),
        activity_task_pollers=1,
        decision_task_pollers=1,
        identity="identity",
    )

    task = asyncio.create_task(worker.run())

    # Wait until both polled
    await both_waited.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    worker_stub.PollForDecisionTask.assert_called_once_with(
        PollForDecisionTaskRequest(
            domain="domain",
            identity="identity",
            task_list=TaskList(
                name="task_list", kind=TaskListKind.TASK_LIST_KIND_NORMAL
            ),
        ),
        timeout=60.0,
    )

    worker_stub.PollForActivityTask.assert_called_once_with(
        PollForActivityTaskRequest(
            domain="domain",
            identity="identity",
            task_list=TaskList(
                name="task_list", kind=TaskListKind.TASK_LIST_KIND_NORMAL
            ),
        ),
        timeout=60.0,
    )
