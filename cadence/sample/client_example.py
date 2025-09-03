import asyncio


from cadence.client import Client
from cadence.worker import Worker, Registry


async def main():
    client = Client(target="localhost:7833", domain="foo")
    worker = Worker(client, "task_list", Registry())
    await worker.run()

if __name__ == '__main__':
    asyncio.run(main())
