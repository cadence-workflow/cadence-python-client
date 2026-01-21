import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Unpack

from cadence import Registry
from cadence.client import ClientOptions, Client
from cadence.worker import WorkerOptions, Worker

DOMAIN_NAME = "test-domain"


class CadenceHelper:
    def __init__(self, options: ClientOptions, test_name: str) -> None:
        self.options = options
        self.test_name = test_name

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

    def client(self):
        return Client(**self.options)
