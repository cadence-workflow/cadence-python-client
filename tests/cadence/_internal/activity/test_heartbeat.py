from unittest.mock import AsyncMock

import pytest

from cadence._internal.activity._heartbeat import _HeartbeatSender
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.service_worker_pb2 import (
    RecordActivityTaskHeartbeatRequest,
    RecordActivityTaskHeartbeatResponse,
)
from cadence.data_converter import DefaultDataConverter


@pytest.fixture
def data_converter() -> DefaultDataConverter:
    return DefaultDataConverter()


@pytest.fixture
def worker_stub() -> AsyncMock:
    stub = AsyncMock()
    stub.RecordActivityTaskHeartbeat = AsyncMock(
        return_value=RecordActivityTaskHeartbeatResponse()
    )
    return stub


@pytest.fixture
def sender(worker_stub, data_converter) -> _HeartbeatSender:
    return _HeartbeatSender(
        worker_stub=worker_stub,
        data_converter=data_converter,
        task_token=b"task_token",
        identity="test-identity",
        previous_details=Payload(),
    )


async def test_heartbeat_sends_rpc(sender, worker_stub):
    await sender.send_heartbeat()

    worker_stub.RecordActivityTaskHeartbeat.assert_called_once_with(
        RecordActivityTaskHeartbeatRequest(
            task_token=b"task_token",
            details=Payload(data=b""),
            identity="test-identity",
        )
    )


async def test_heartbeat_with_details(sender, worker_stub):
    await sender.send_heartbeat("progress", 42)

    worker_stub.RecordActivityTaskHeartbeat.assert_called_once_with(
        RecordActivityTaskHeartbeatRequest(
            task_token=b"task_token",
            details=Payload(data=b'"progress" 42'),
            identity="test-identity",
        )
    )


async def test_heartbeat_no_details(sender, worker_stub):
    await sender.send_heartbeat()

    worker_stub.RecordActivityTaskHeartbeat.assert_called_once()
    call = worker_stub.RecordActivityTaskHeartbeat.call_args[0][0]
    assert call.task_token == b"task_token"
    assert call.identity == "test-identity"


async def test_heartbeat_updates_previous_details(sender, worker_stub):
    await sender.send_heartbeat("step1", 10)

    details = sender.get_details(str, int)
    assert details == ["step1", 10]


async def test_heartbeat_details_not_updated_on_failure(
    worker_stub, data_converter,
):
    worker_stub.RecordActivityTaskHeartbeat = AsyncMock(
        side_effect=Exception("rpc error")
    )
    sender = _HeartbeatSender(
        worker_stub=worker_stub,
        data_converter=data_converter,
        task_token=b"task_token",
        identity="test-identity",
        previous_details=Payload(data=b'"old"'),
    )

    await sender.send_heartbeat("new_value")

    details = sender.get_details(str)
    assert details == ["old"]
