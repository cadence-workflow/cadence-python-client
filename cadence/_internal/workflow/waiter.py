from asyncio import AbstractEventLoop, Future
from typing import Callable, Any, Generator, Awaitable


class Waiter(Awaitable[None]):
    """Awaitable that resolves when ``predicate()`` becomes truthy."""

    __slots__ = ("_predicate", "_future")

    def __init__(self, predicate: Callable[[], bool], loop: AbstractEventLoop) -> None:
        self._predicate = predicate
        self._future: Future[None] = loop.create_future()

    def __await__(self) -> Generator[Any, None, None]:
        return self._future.__await__()

    def done(self) -> bool:
        return self._future.done()

    def exception(self) -> BaseException | None:
        return self._future.exception()

    def result(self) -> None:
        self._future.result()

    def poll(self) -> bool:
        """Re-evaluate the predicate. Returns True when settled (and evictable)."""
        if self._future.done():
            return True
        try:
            if self._predicate():
                self._future.set_result(None)
                return True
            return False
        except BaseException as exc:
            self._future.set_exception(exc)
            return True
