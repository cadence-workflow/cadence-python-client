from asyncio import AbstractEventLoop, Handle, futures, tasks
from contextvars import Context
import logging
import collections
import asyncio.events as events
import threading
from typing import Callable
from typing_extensions import Unpack, TypeVarTuple

logger = logging.getLogger(__name__)

_Ts = TypeVarTuple("_Ts")

class DeterministicEventLoop(AbstractEventLoop):
    """
    This is a basic FIFO implementation of event loop that does not allow I/O or timer operations.
    As a result, it's theoretically deterministic. This event loop is not useful directly without async events processing inside the loop.

    Code is mostly copied from asyncio.BaseEventLoop without I/O or timer operations.
    """

    def __init__(self):
        self._thread_id = None # indicate if the event loop is running
        self._debug = False
        self._ready  = collections.deque[events.Handle]()
        self._stopping = False
        self._closed = False

    def call_soon(self, callback: Callable[[Unpack[_Ts]], object], *args: Unpack[_Ts], context: Context | None = None) -> Handle:
        return self._call_soon(callback, args, context)

    def _call_soon(self, callback, args, context) -> Handle:
        handle = events.Handle(callback, args, self, context)
        self._ready.append(handle)
        return handle

    def get_debug(self):
        return self._debug


    def run_forever(self):
        """Run until stop() is called."""
        self._run_forever_setup()
        try:
            while True:
                self._run_once()
                if self._stopping:
                    break
        finally:
            self._run_forever_cleanup()

    def run_until_complete(self, future):
        """Run until the Future is done.

        If the argument is a coroutine, it is wrapped in a Task.

        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.

        Return the Future's result, or raise its exception.
        """
        self._check_closed()
        self._check_running()

        new_task = not futures.isfuture(future)
        future = tasks.ensure_future(future, loop=self)

        future.add_done_callback(_run_until_complete_cb)
        try:
            self.run_forever()
        except:
            if new_task and future.done() and not future.cancelled():
                # The coroutine raised a BaseException. Consume the exception
                # to not log a warning, the caller doesn't have access to the
                # local task.
                future.exception()
            raise
        finally:
            future.remove_done_callback(_run_until_complete_cb)
        if not future.done():
            raise RuntimeError('Event loop stopped before Future completed.')

        return future.result()

    def create_task(self, coro, **kwargs):
        """Schedule a coroutine object.

        Return a task object.
        """
        self._check_closed()

        # NOTE: eager_start is not supported for deterministic event loop
        if kwargs.get("eager_start", False):
            raise RuntimeError("eager_start in create_task is not supported for deterministic event loop")

        return tasks.Task(coro, loop=self, **kwargs)

    def create_future(self):
        return futures.Future(loop=self)

    def _run_once(self):
        ntodo = len(self._ready)
        for i in range(ntodo):
            handle = self._ready.popleft()
            if handle._cancelled:
                continue
            handle._run()

    def _run_forever_setup(self):
        self._check_closed()
        self._check_running()
        self._thread_id = threading.get_ident()
        events._set_running_loop(self)

    def _run_forever_cleanup(self):
        self._stopping = False
        self._thread_id = None
        events._set_running_loop(None)

    def stop(self):
        self._stopping = True

    def _check_closed(self):
        if self._closed:
            raise RuntimeError('Event loop is closed')

    def _check_running(self):
        if self.is_running():
            raise RuntimeError('This event loop is already running')
        if events._get_running_loop() is not None:
            raise RuntimeError(
                'Cannot run the event loop while another loop is running')

    def is_running(self):
        return (self._thread_id is not None)

    def close(self):
        """Close the event loop.
        The event loop must not be running.
        """
        if self.is_running():
            raise RuntimeError("Cannot close a running event loop")
        if self._closed:
            return
        if self._debug:
            logger.debug("Close %r", self)
        self._closed = True
        self._ready.clear()

    def is_closed(self):
        """Returns True if the event loop was closed."""
        return self._closed

def _run_until_complete_cb(fut):
    if not fut.cancelled():
        exc = fut.exception()
        if isinstance(exc, (SystemExit, KeyboardInterrupt)):
            return
    fut.get_loop().stop()
