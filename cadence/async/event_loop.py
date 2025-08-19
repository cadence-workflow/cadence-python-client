

from asyncio import AbstractEventLoop, BaseEventLoop, EventLoop
from asyncio import Future
import asyncio

class EventLoop(BaseEventLoop):
    __running = False

    def __init__(self):
        super().__init__()

    def run_until_complete(self, future: Future):
        pass

    def start(self):
        self.__running = True

    def is_running(self):
        return self.__running

async def workflow():
    asyncio.set_event_loop(EventLoop())

    task1 = asyncio.create_task(delay_print("Hello, world!", 1))
    task2 = asyncio.create_task(delay_print("Hello, world!", 1))
    await task1
    await task2


async def delay_print(message, delay):
    await asyncio.sleep(delay)
    print(message)


class DeterministicRunner():
    runner = None

    def run_util_block

if __name__ == "__main__":
    print("Starting workflow")
    loop = asyncio.new_event_loop()
    loop.start()
    loop.run_until_complete(workflow())
