from asyncio import AbstractEventLoop
from typing import Callable

from cadence.workflow import WorkflowFuture


class Waiter(WorkflowFuture[None]):
    """Future that resolves when ``predicate()`` becomes truthy."""

    __slots__ = ("_predicate",)

    def __init__(self, predicate: Callable[[], bool], loop: AbstractEventLoop) -> None:
        super().__init__(loop=loop)
        self._predicate = predicate

    def poll(self) -> bool:
        """Re-evaluate the predicate. Returns True when settled (and evictable)."""
        if self.done():
            return True
        try:
            if self._predicate():
                self.set_result(None)
                return True
            return False
        except BaseException as exc:
            self.set_exception(exc)
            return True
