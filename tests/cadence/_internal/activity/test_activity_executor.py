import asyncio
from datetime import timedelta, datetime
from unittest.mock import Mock, AsyncMock, PropertyMock

import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from google.protobuf.duration import from_timedelta

from cadence import activity, Client
from cadence._internal.activity import ActivityExecutor
from cadence.activity import ActivityInfo, ActivityDefinition
from cadence.api.v1.common_pb2 import (
    WorkflowExecution,
    ActivityType,
    Payload,
    Failure,
    WorkflowType,
)
from cadence.api.v1.service_worker_pb2 import (
    RespondActivityTaskCompletedResponse,
    PollForActivityTaskResponse,
    RespondActivityTaskCompletedRequest,
    RespondActivityTaskFailedResponse,
    RespondActivityTaskFailedRequest,
)
from cadence.data_converter import DefaultDataConverter
from cadence.worker import Registry


@pytest.fixture
def client() -> Client:
    client = Mock(spec=Client)
    client.worker_stub = AsyncMock()
    type(client).data_converter = PropertyMock(return_value=DefaultDataConverter())
    return client


async def test_activity_async_success(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskCompleted = AsyncMock(
        return_value=RespondActivityTaskCompletedResponse()
    )

    reg = Registry()

    @reg.activity(name="activity_type")
    async def activity_fn():
        return "success"

    executor = ActivityExecutor(client, "task_list", "identity", 1, reg.get_activity)

    await executor.execute(fake_task("activity_type", ""))

    worker_stub.RespondActivityTaskCompleted.assert_called_once_with(
        RespondActivityTaskCompletedRequest(
            task_token=b"task_token",
            result=Payload(data='"success"'.encode()),
            identity="identity",
        )
    )


async def test_activity_async_failure(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskFailed = AsyncMock(
        return_value=RespondActivityTaskFailedResponse()
    )

    reg = Registry()

    @reg.activity(name="activity_type")
    async def activity_fn():
        raise KeyError("failure")

    executor = ActivityExecutor(client, "task_list", "identity", 1, reg.get_activity)

    await executor.execute(fake_task("activity_type", ""))

    worker_stub.RespondActivityTaskFailed.assert_called_once()

    call = worker_stub.RespondActivityTaskFailed.call_args[0][0]

    # Confirm it's a stacktrace, then clear it since it is different on every machine
    assert 'raise KeyError("failure")' in call.failure.details.decode()
    call.failure.details = bytes()
    assert call == RespondActivityTaskFailedRequest(
        task_token=b"task_token",
        failure=Failure(
            reason="KeyError",
        ),
        identity="identity",
    )


async def test_activity_args(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskCompleted = AsyncMock(
        return_value=RespondActivityTaskCompletedResponse()
    )

    reg = Registry()

    @reg.activity(name="activity_type")
    async def activity_fn(first: str, second: str):
        return " ".join([first, second])

    executor = ActivityExecutor(client, "task_list", "identity", 1, reg.get_activity)

    await executor.execute(fake_task("activity_type", '"hello" "world"'))

    worker_stub.RespondActivityTaskCompleted.assert_called_once_with(
        RespondActivityTaskCompletedRequest(
            task_token=b"task_token",
            result=Payload(data='"hello world"'.encode()),
            identity="identity",
        )
    )


async def test_activity_sync_success(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskCompleted = AsyncMock(
        return_value=RespondActivityTaskCompletedResponse()
    )

    reg = Registry()

    @reg.activity(name="activity_type")
    def activity_fn():
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return "success"
        raise RuntimeError("expected to be running outside of the event loop")

    executor = ActivityExecutor(client, "task_list", "identity", 1, reg.get_activity)

    await executor.execute(fake_task("activity_type", ""))

    worker_stub.RespondActivityTaskCompleted.assert_called_once_with(
        RespondActivityTaskCompletedRequest(
            task_token=b"task_token",
            result=Payload(data='"success"'.encode()),
            identity="identity",
        )
    )


async def test_activity_sync_failure(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskFailed = AsyncMock(
        return_value=RespondActivityTaskFailedResponse()
    )
    reg = Registry()

    @reg.activity(name="activity_type")
    def activity_fn():
        raise KeyError("failure")

    executor = ActivityExecutor(client, "task_list", "identity", 1, reg.get_activity)

    await executor.execute(fake_task("activity_type", ""))

    worker_stub.RespondActivityTaskFailed.assert_called_once()

    call = worker_stub.RespondActivityTaskFailed.call_args[0][0]

    # Confirm it's a stacktrace, then clear it since it is different on every machine
    assert 'raise KeyError("failure")' in call.failure.details.decode()
    call.failure.details = bytes()
    assert call == RespondActivityTaskFailedRequest(
        task_token=b"task_token",
        failure=Failure(
            reason="KeyError",
        ),
        identity="identity",
    )


async def test_activity_unknown(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskFailed = AsyncMock(
        return_value=RespondActivityTaskFailedResponse()
    )

    def registry(name: str) -> ActivityDefinition:
        raise KeyError(f"unknown activity: {name}")

    executor = ActivityExecutor(client, "task_list", "identity", 1, registry)

    await executor.execute(fake_task("activity_type", ""))

    worker_stub.RespondActivityTaskFailed.assert_called_once()

    call = worker_stub.RespondActivityTaskFailed.call_args[0][0]

    assert "Activity type not found: activity_type" in call.failure.details.decode()
    call.failure.details = bytes()
    assert call == RespondActivityTaskFailedRequest(
        task_token=b"task_token",
        failure=Failure(
            reason="KeyError",
        ),
        identity="identity",
    )


async def test_activity_context(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskCompleted = AsyncMock(
        return_value=RespondActivityTaskCompletedResponse()
    )
    reg = Registry()

    @reg.activity(name="activity_type")
    async def activity_fn():
        assert fake_info("activity_type") == activity.info()
        assert activity.in_activity()
        assert activity.client() is not None
        return "success"

    executor = ActivityExecutor(client, "task_list", "identity", 1, reg.get_activity)

    await executor.execute(fake_task("activity_type", ""))

    worker_stub.RespondActivityTaskCompleted.assert_called_once_with(
        RespondActivityTaskCompletedRequest(
            task_token=b"task_token",
            result=Payload(data='"success"'.encode()),
            identity="identity",
        )
    )


async def test_activity_context_sync(client):
    worker_stub = client.worker_stub
    worker_stub.RespondActivityTaskCompleted = AsyncMock(
        return_value=RespondActivityTaskCompletedResponse()
    )

    reg = Registry()

    @reg.activity(name="activity_type")
    def activity_fn():
        assert fake_info("activity_type") == activity.info()
        assert activity.in_activity()
        with pytest.raises(RuntimeError):
            activity.client()
        return "success"

    executor = ActivityExecutor(client, "task_list", "identity", 1, reg.get_activity)

    await executor.execute(fake_task("activity_type", ""))

    worker_stub.RespondActivityTaskCompleted.assert_called_once_with(
        RespondActivityTaskCompletedRequest(
            task_token=b"task_token",
            result=Payload(data='"success"'.encode()),
            identity="identity",
        )
    )


def fake_info(activity_type: str) -> ActivityInfo:
    return ActivityInfo(
        task_token=b"task_token",
        workflow_domain="workflow_domain",
        workflow_id="workflow_id",
        workflow_run_id="run_id",
        activity_id="activity_id",
        activity_type=activity_type,
        attempt=1,
        workflow_type="workflow_type",
        task_list="task_list",
        heartbeat_timeout=timedelta(seconds=1),
        scheduled_timestamp=datetime(2020, 1, 2, 3),
        started_timestamp=datetime(2020, 1, 2, 4),
        start_to_close_timeout=timedelta(seconds=2),
    )


def fake_task(activity_type: str, input_json: str) -> PollForActivityTaskResponse:
    return PollForActivityTaskResponse(
        task_token=b"task_token",
        workflow_domain="workflow_domain",
        workflow_type=WorkflowType(name="workflow_type"),
        workflow_execution=WorkflowExecution(
            workflow_id="workflow_id",
            run_id="run_id",
        ),
        activity_id="activity_id",
        activity_type=ActivityType(name=activity_type),
        input=Payload(data=input_json.encode()),
        attempt=1,
        heartbeat_timeout=from_timedelta(timedelta(seconds=1)),
        scheduled_time=from_datetime(datetime(2020, 1, 2, 3)),
        started_time=from_datetime(datetime(2020, 1, 2, 4)),
        start_to_close_timeout=from_timedelta(timedelta(seconds=2)),
    )


def from_datetime(time: datetime) -> Timestamp:
    t = Timestamp()
    t.FromDatetime(time)
    return t
