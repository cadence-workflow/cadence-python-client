import asyncio
from unittest.mock import Mock, AsyncMock, PropertyMock

import pytest

from cadence import Client
from cadence._internal.activity import ActivityExecutor
from cadence.api.v1.common_pb2 import WorkflowExecution, ActivityType, Payload, Failure
from cadence.api.v1.service_worker_pb2 import RespondActivityTaskCompletedResponse, PollForActivityTaskResponse, \
    RespondActivityTaskCompletedRequest, RespondActivityTaskFailedResponse, RespondActivityTaskFailedRequest
from cadence.data_converter import DefaultDataConverter


@pytest.fixture
def client() -> Client:
    client = Mock(spec=Client)
    client.worker_stub = AsyncMock()
    type(client).data_converter = PropertyMock(return_value=DefaultDataConverter())
    return client


@pytest.mark.asyncio
async def test_activity_async_success(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskCompleted = AsyncMock(return_value=RespondActivityTaskCompletedResponse())

    async def activity_fn():
        return "success"

    executor = ActivityExecutor(client, 'task_list', 'identity', 1, lambda name: activity_fn)

    await executor.execute(fake_task("any", ""))

    worker_stub.RespondActivityTaskCompleted.assert_called_once_with(RespondActivityTaskCompletedRequest(
        task_token=b'task_token',
        result=Payload(data='"success"'.encode()),
        identity='identity',
    ))

@pytest.mark.asyncio
async def test_activity_async_failure(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskFailed = AsyncMock(return_value=RespondActivityTaskFailedResponse())

    async def activity_fn():
        raise KeyError("failure")

    executor = ActivityExecutor(client, 'task_list', 'identity', 1, lambda name: activity_fn)

    await executor.execute(fake_task("any", ""))

    worker_stub.RespondActivityTaskFailed.assert_called_once()

    call = worker_stub.RespondActivityTaskFailed.call_args[0][0]

    # Confirm it's a stacktrace, then clear it since it is different on every machine
    assert 'raise KeyError("failure")' in call.failure.details.decode()
    call.failure.details = bytes()
    assert call == RespondActivityTaskFailedRequest(
        task_token=b'task_token',
        failure=Failure(
            reason="KeyError",
        ),
        identity='identity',
    )

@pytest.mark.asyncio
async def test_activity_args(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskCompleted = AsyncMock(return_value=RespondActivityTaskCompletedResponse())

    async def activity_fn(first: str, second: str):
        return " ".join([first, second])

    executor = ActivityExecutor(client, 'task_list', 'identity', 1, lambda name: activity_fn)

    await executor.execute(fake_task("any", '["hello", "world"]'))

    worker_stub.RespondActivityTaskCompleted.assert_called_once_with(RespondActivityTaskCompletedRequest(
        task_token=b'task_token',
        result=Payload(data='"hello world"'.encode()),
        identity='identity',
    ))


@pytest.mark.asyncio
async def test_activity_sync_success(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskCompleted = AsyncMock(return_value=RespondActivityTaskCompletedResponse())

    def activity_fn():
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return "success"
        raise RuntimeError("expected to be running outside of the event loop")

    executor = ActivityExecutor(client, 'task_list', 'identity', 1, lambda name: activity_fn)

    await executor.execute(fake_task("any", ""))

    worker_stub.RespondActivityTaskCompleted.assert_called_once_with(RespondActivityTaskCompletedRequest(
        task_token=b'task_token',
        result=Payload(data='"success"'.encode()),
        identity='identity',
    ))

@pytest.mark.asyncio
async def test_activity_sync_failure(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskFailed = AsyncMock(return_value=RespondActivityTaskFailedResponse())

    def activity_fn():
        raise KeyError("failure")

    executor = ActivityExecutor(client, 'task_list', 'identity', 1, lambda name: activity_fn)

    await executor.execute(fake_task("any", ""))

    worker_stub.RespondActivityTaskFailed.assert_called_once()

    call = worker_stub.RespondActivityTaskFailed.call_args[0][0]

    # Confirm it's a stacktrace, then clear it since it is different on every machine
    assert 'raise KeyError("failure")' in call.failure.details.decode()
    call.failure.details = bytes()
    assert call == RespondActivityTaskFailedRequest(
        task_token=b'task_token',
        failure=Failure(
            reason="KeyError",
        ),
        identity='identity',
    )

@pytest.mark.asyncio
async def test_activity_unknown(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskFailed = AsyncMock(return_value=RespondActivityTaskFailedResponse())

    def registry(name: str):
        raise KeyError(f"unknown activity: {name}")

    executor = ActivityExecutor(client, 'task_list', 'identity', 1, registry)

    await executor.execute(fake_task("any", ""))

    worker_stub.RespondActivityTaskFailed.assert_called_once()

    call = worker_stub.RespondActivityTaskFailed.call_args[0][0]

    assert 'unknown activity: any' in call.failure.details.decode()
    call.failure.details = bytes()
    assert call == RespondActivityTaskFailedRequest(
        task_token=b'task_token',
        failure=Failure(
            reason="KeyError",
        ),
        identity='identity',
    )

def fake_task(activity_type: str, input_json: str) -> PollForActivityTaskResponse:
    return PollForActivityTaskResponse(
        task_token=b'task_token',
        workflow_execution=WorkflowExecution(
            workflow_id="workflow_id",
            run_id="run_id",
        ),
        activity_id="activity_id",
        activity_type=ActivityType(name=activity_type),
        input=Payload(data=input_json.encode()),
        attempt=0,
    )