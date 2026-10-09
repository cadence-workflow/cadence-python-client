import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Polling never stops on errors, it only slows down.
_POLL_BACKOFF_INITIAL_INTERVAL = timedelta(milliseconds=20)
_POLL_BACKOFF_COEFFICIENT = 2.0
_POLL_BACKOFF_MAX_INTERVAL = timedelta(seconds=10)
_POLL_BACKOFF_JITTER = 0.2


class Poller(Generic[T]):
    def __init__(
        self,
        num_tasks: int,
        permits: asyncio.Semaphore,
        poll: Callable[[], Awaitable[T | None]],
        callback: Callable[[T], Awaitable[None]],
        on_start: Callable[[int], None] | None = None,
    ) -> None:
        self._num_tasks = num_tasks
        self._permits = permits
        self._poll = poll
        self._callback = callback
        self._on_start = on_start
        self._background_tasks: set[asyncio.Task[None]] = set()
        # Shared by all poll loops so they back off together
        self._poll_backoff: timedelta | None = None

    async def run(self) -> None:
        try:
            async with asyncio.TaskGroup() as tg:
                for _ in range(self._num_tasks):
                    tg.create_task(self._poll_loop())
                if self._on_start is not None:
                    self._on_start(self._num_tasks)
        except asyncio.CancelledError:
            pass

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_and_dispatch()
                self._poll_backoff = None
            except asyncio.CancelledError as e:
                raise e
            except Exception:
                self._poll_backoff = _next_poll_backoff(self._poll_backoff)
                logger.exception("Exception while polling")

    async def _poll_and_dispatch(self) -> None:
        await self._permits.acquire()
        if self._poll_backoff is not None:
            await asyncio.sleep(_with_jitter(self._poll_backoff))
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


def _next_poll_backoff(current: timedelta | None) -> timedelta:
    if current is None:
        return _POLL_BACKOFF_INITIAL_INTERVAL
    return min(current * _POLL_BACKOFF_COEFFICIENT, _POLL_BACKOFF_MAX_INTERVAL)


def _with_jitter(delay: timedelta) -> float:
    delay_seconds = delay.total_seconds()
    jitter_seconds = random.uniform(0, _POLL_BACKOFF_JITTER * delay_seconds)
    return delay_seconds * (1 - _POLL_BACKOFF_JITTER) + jitter_seconds
