from typing import Any

from cadence.api.v1.service_worker_pb2 import RecordActivityTaskHeartbeatRequest
from cadence.data_converter import DataConverter


class _HeartbeatSender:
    def __init__(
        self,
        worker_stub: Any,
        data_converter: DataConverter,
        task_token: bytes,
        identity: str,
    ):
        self._worker_stub = worker_stub
        self._data_converter = data_converter
        self._task_token = task_token
        self._identity = identity

    async def send_heartbeat(self, *details: Any) -> None:
        payload = self._data_converter.to_data(list(details))
        await self._worker_stub.RecordActivityTaskHeartbeat(
            RecordActivityTaskHeartbeatRequest(
                task_token=self._task_token,
                details=payload,
                identity=self._identity,
            )
        )
