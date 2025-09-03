import os
import socket
from typing import TypedDict, Unpack, Any, cast

from grpc import ChannelCredentials, Compression

from cadence._internal.rpc.yarpc import YarpcMetadataInterceptor
from cadence.api.v1.service_worker_pb2_grpc import WorkerAPIStub
from grpc.aio import Channel, ClientInterceptor, secure_channel, insecure_channel
from cadence.data_converter import DataConverter, DefaultDataConverter


class ClientOptions(TypedDict, total=False):
    domain: str
    target: str
    data_converter: DataConverter
    identity: str
    service_name: str
    caller_name: str
    channel_arguments: dict[str, Any]
    credentials: ChannelCredentials | None
    compression: Compression
    interceptors: list[ClientInterceptor]

_DEFAULT_OPTIONS: ClientOptions = {
    "data_converter": DefaultDataConverter(),
    "identity": f"{os.getpid()}@{socket.gethostname()}",
    "service_name": "cadence-frontend",
    "caller_name": "cadence-client",
    "channel_arguments": {},
    "credentials": None,
    "compression": Compression.NoCompression,
    "interceptors": [],
}

class Client:
    def __init__(self, **kwargs: Unpack[ClientOptions]) -> None:
        self._options = _validate_and_copy_defaults(ClientOptions(**kwargs))
        self._channel = _create_channel(self._options)
        self._worker_stub = WorkerAPIStub(self._channel)

    @property
    def data_converter(self) -> DataConverter:
        return self._options["data_converter"]

    @property
    def domain(self) -> str:
        return self._options["domain"]

    @property
    def identity(self) -> str:
        return self._options["identity"]

    @property
    def worker_stub(self) -> WorkerAPIStub:
        return self._worker_stub

    async def close(self) -> None:
        await self._channel.close()

def _validate_and_copy_defaults(options: ClientOptions) -> ClientOptions:
    if "target" not in options:
        raise ValueError("target must be specified")

    if "domain" not in options:
        raise ValueError("domain must be specified")

    # Set default values for missing options
    for key, value in _DEFAULT_OPTIONS.items():
        if key not in options:
            cast(dict, options)[key] = value

    return options


def _create_channel(options: ClientOptions) -> Channel:
    interceptors = list(options["interceptors"])
    interceptors.append(YarpcMetadataInterceptor(options["service_name"], options["caller_name"]))

    if options["credentials"]:
        return secure_channel(options["target"], options["credentials"], options["channel_arguments"], options["compression"], interceptors)
    else:
        return insecure_channel(options["target"], options["channel_arguments"], options["compression"], interceptors)