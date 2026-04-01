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
