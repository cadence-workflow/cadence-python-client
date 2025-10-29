import asyncio
import logging
from typing import Callable, TypeVar, Generic, Awaitable, Optional

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Poller(Generic[T]):
    def __init__(
        self,
        num_tasks: int,
        permits: asyncio.Semaphore,
        poll: Callable[[], Awaitable[Optional[T]]],
        callback: Callable[[T], Awaitable[None]],
    ) -> None:
        self._num_tasks = num_tasks
        self._permits = permits
        self._poll = poll
        self._callback = callback
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        try:
            async with asyncio.TaskGroup() as tg:
                for i in range(self._num_tasks):
                    tg.create_task(self._poll_loop())
        except asyncio.CancelledError:
            pass

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_and_dispatch()
            except asyncio.CancelledError as e:
                raise e
            except Exception:
                logger.exception("Exception while polling")

    async def _poll_and_dispatch(self) -> None:
        await self._permits.acquire()
        try:
            task = await self._poll()
        except Exception as e:
            self._permits.release()
            raise e

        if task is None:
            self._permits.release()
            return

        # Need to store a reference to the async task or it may be garbage collected
        scheduled = asyncio.create_task(self._execute_callback(task))
        self._background_tasks.add(scheduled)
        scheduled.add_done_callback(self._background_tasks.remove)

    async def _execute_callback(self, task: T) -> None:
        try:
            await self._callback(task)
        except Exception:
            logger.exception("Exception during callback")
        finally:
            self._permits.release()
