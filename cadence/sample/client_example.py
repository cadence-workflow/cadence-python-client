import asyncio

from grpc.aio import insecure_channel, Metadata

from cadence.client import Client, ClientOptions
from cadence._internal.rpc.metadata import MetadataInterceptor
from cadence.worker import Worker


async def main():
    # TODO - Hide all this
    metadata = Metadata()
    metadata["rpc-service"] = "cadence-frontend"
    metadata["rpc-encoding"] = "proto"
    metadata["rpc-caller"] = "nate"
    async with insecure_channel("localhost:7833", interceptors=[MetadataInterceptor(metadata)]) as channel:
        client = Client(channel, ClientOptions(domain="foo"))
        worker = Worker(client, "task_list")
        await worker.run()

if __name__ == '__main__':
    asyncio.run(main())
