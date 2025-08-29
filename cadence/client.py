import os
import socket
from typing import TypedDict

from cadence.api.v1.service_worker_pb2_grpc import WorkerAPIStub
from grpc.aio import Channel

from cadence.data_converter import DataConverter


class ClientOptions(TypedDict, total=False):
    domain: str
    identity: str
    data_converter: DataConverter

class Client:
    def __init__(self, channel: Channel, options: ClientOptions) -> None:
        self._channel = channel
        self._worker_stub = WorkerAPIStub(channel)
        self._options = options
        self._identity = options["identity"] if "identity" in options else f"{os.getpid()}@{socket.gethostname()}"

    @property
    def data_converter(self) -> DataConverter:
        return self._options["data_converter"]

    @property
    def domain(self) -> str:
        return self._options["domain"]

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def worker_stub(self) -> WorkerAPIStub:
        return self._worker_stub


    async def close(self) -> None:
        await self._channel.close()


