import asyncio


from cadence.client import Client
from cadence.worker import Worker, Registry


async def main():
    async with Client(target="localhost:7833", domain="foo") as client:
        worker = Worker(client, "task_list", Registry())
        await worker.run()

if __name__ == '__main__':
    asyncio.run(main())
