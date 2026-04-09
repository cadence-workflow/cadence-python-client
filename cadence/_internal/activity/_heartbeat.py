from logging import getLogger
from typing import Any, Type

from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.service_worker_pb2 import RecordActivityTaskHeartbeatRequest
from cadence.api.v1.service_worker_pb2_grpc import WorkerAPIStub
from cadence.data_converter import DataConverter

_logger = getLogger(__name__)


class _HeartbeatSender:
    def __init__(
        self,
        worker_stub: WorkerAPIStub,
        data_converter: DataConverter,
        task_token: bytes,
        identity: str,
        previous_details: Payload,
    ):
        self._worker_stub = worker_stub
        self._data_converter = data_converter
        self._task_token = task_token
        self._identity = identity
        self._previous_details = previous_details

    def get_details(self, *types: Type) -> list[Any]:
        return self._data_converter.from_data(self._previous_details, list(types))

    async def send_heartbeat(self, *details: Any) -> None:
        try:
            payload = self._data_converter.to_data(list(details))
            await self._worker_stub.RecordActivityTaskHeartbeat(
                RecordActivityTaskHeartbeatRequest(
                    task_token=self._task_token,
                    details=payload,
                    identity=self._identity,
                )
            )
            self._previous_details = payload
        except Exception:
            _logger.warning("Heartbeat failed", exc_info=True)
