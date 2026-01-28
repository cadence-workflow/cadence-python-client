import asyncio
import pathlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Unpack, cast

from google.protobuf.proto_json import serialize, parse
from msgspec import json
from cadence import Registry
from cadence.api.v1 import history
from cadence.client import ClientOptions, Client
from cadence.worker import WorkerOptions, Worker

DOMAIN_NAME = "test-domain"


class CadenceHelper:
    def __init__(self, options: ClientOptions, test_name: str, fspath: str) -> None:
        self.options = options
        self.test_name = test_name
        self.fspath = fspath

    @asynccontextmanager
    async def worker(
        self, registry: Registry, **kwargs: Unpack[WorkerOptions]
    ) -> AsyncGenerator[Worker, None]:
        async with self.client() as client:
            worker = Worker(client, self.test_name, registry, **kwargs)
            task = asyncio.create_task(worker.run())
            yield worker
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def load_history(self, path: str) -> history.History:
        file = pathlib.Path(self.fspath).with_name(path)
        with file.open("rb") as fp:
            as_json = json.decode(fp.read())
            return cast(history.History, parse(history.History, as_json))

    # This isn't useful in a test, but it's useful while writing tests.
    def write_history(self, path: str, h: history.History) -> None:
        file = pathlib.Path(self.fspath).with_name(path)
        with file.open("wb") as fp:
            as_json = json.encode(serialize(h, preserving_proto_field_name=True))
            fp.write(as_json)

    def client(self):
        return Client(**self.options)
