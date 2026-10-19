import inspect
import traceback
import weakref
from asyncio import (
    AbstractEventLoop,
    CancelledError,
    Handle,
    TimerHandle,
    futures,
    tasks,
    Future,
    Task,
)
from contextvars import Context, copy_context
import logging
import collections
import asyncio.events as events
import threading
from typing import Callable, Any, TypeVar, Coroutine, Awaitable, Generator, NoReturn
from typing_extensions import Unpack, TypeVarTuple

from cadence._internal.workflow.waiter import Waiter

logger = logging.getLogger(__name__)


class FatalDecisionError(BaseException):
    """Fails the decision task rather than the workflow.

    Extends BaseException so that ``except Exception`` in workflow code doesn't
    swallow it.
    """

    def __init__(self, *args) -> None:
        super().__init__(*args)


class DecisionAbortedError(FatalDecisionError):
    """Raised in workflow code once the decision has failed or the loop is closing.

    Its ``__cause__`` is the original failure, if any. The original is never raised
    inside workflow code, so its traceback and context are reported unchanged.
    """


def fail_decision(error: FatalDecisionError) -> NoReturn:
    """Mark the running decision as failed and raise error.

    The DeterministicEventLoop stops running workflow code and re-raises error,
    so the decision task fails even if workflow code catches it.
    """
    loop = events._get_running_loop()
    if isinstance(loop, DeterministicEventLoop):
        loop.fail_decision(error)
    raise error


_Ts = TypeVarTuple("_Ts")
_T = TypeVar("_T")


class DeterministicEventLoop(AbstractEventLoop):
    """
    This is a basic FIFO implementation of event loop that does not allow I/O or timer operations.
    As a result, it's theoretically deterministic. This event loop is not useful directly without async events processing inside the loop.

    Code is mostly copied from asyncio.BaseEventLoop without I/O or timer operations.
    """

    def __init__(self) -> None:
        self._thread_id: int | None = None  # indicate if the event loop is running
        self._debug: bool = False
        self._ready: collections.deque[events.Handle] = collections.deque()
        self._waiters: list[Waiter] = []
        self._stopping: bool = False
        self._closed: bool = False
        self._decision_failure: FatalDecisionError | None = None
        # Insertion-ordered so close() unwinds tasks deterministically.
        self._tasks: weakref.WeakValueDictionary[int, _DeterministicTask[Any]] = (
            weakref.WeakValueDictionary()
        )
        self._task_seq: int = 0

    def run_until_yield(self):
        """Run until there is no ready work.

        Raises the FatalDecisionError passed to fail_decision(), if any.
        """
        self._run_forever_setup()
        try:
            while self._ready and self._decision_failure is None:
                self._run_once()
        finally:
            self._run_forever_cleanup()
        if self._decision_failure is not None:
            raise self._decision_failure

    def fail_decision(self, error: FatalDecisionError) -> None:
        """Stop running workflow code and fail the decision with error."""
        if self._decision_failure is None:
            self._decision_failure = error

    def abort_if_decision_failed(self) -> None:
        """Raise a DecisionAbortedError in workflow code if the decision has failed
        or the loop is closed."""
        if self._closed or self._decision_failure is not None:
            raise self._abort_error()

    def _abort_error(self) -> DecisionAbortedError:
        failure = self._decision_failure
        if failure is None:
            return DecisionAbortedError("workflow destroyed")
        error = DecisionAbortedError("decision already failed")
        error.__cause__ = failure
        return error

    # Event Loop APIs
    def call_soon(
        self,
        callback: Callable[[Unpack[_Ts]], object],
        *args: Unpack[_Ts],
        context: Context | None = None,
    ) -> Handle:
        return self._call_soon(callback, args, context)

    def _call_soon(
        self,
        callback: Callable[..., Any],
        args: tuple[Any, ...],
        context: Context | None,
    ) -> Handle:
        handle = events.Handle(callback, args, self, context)
        self._ready.append(handle)
        return handle

    def get_debug(self) -> bool:
        return self._debug

    def set_debug(self, enabled: bool) -> None:
        self._debug = enabled

    def run_forever(self) -> None:
        """Run until stop() is called."""
        self._run_forever_setup()
        try:
            while True:
                self._run_once()
                if self._stopping or self._decision_failure is not None:
                    break
        finally:
            self._run_forever_cleanup()
        if self._decision_failure is not None:
            raise self._decision_failure

    def run_until_complete(
        self, future: Generator[Any, None, _T] | Awaitable[_T]
    ) -> _T:
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
        future = tasks.ensure_future(future, loop=self)  # type: ignore[arg-type]

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
            raise RuntimeError("Event loop stopped before Future completed.")

        return future.result()

    def create_task(
        self, coro: Generator[Any, None, _T] | Coroutine[Any, Any, _T], **kwargs: Any
    ) -> Task[_T]:
        """Schedule a coroutine object.

        Return a task object.
        """
        if self._closed or self._decision_failure is not None:
            # The loop won't run again, so the task could never start.
            if inspect.iscoroutine(coro):
                coro.close()
            raise self._abort_error()

        # NOTE: eager_start is not supported for deterministic event loop
        if kwargs.pop("eager_start", False):
            if inspect.iscoroutine(coro):
                coro.close()
            raise RuntimeError(
                "eager_start in create_task is not supported for deterministic event loop"
            )

        task = _DeterministicTask(coro, loop=self, **kwargs)
        self._tasks[self._task_seq] = task
        self._task_seq += 1
        return task

    def create_future(self) -> Future[Any]:
        return futures.Future(loop=self)

    def create_waiter(self, predicate: Callable[[], bool]) -> Waiter:
        """Register a predicate-driven awaitable."""
        waiter = Waiter(predicate, self)
        if not waiter.poll():
            self._waiters.append(waiter)
        return waiter

    def _run_once(self) -> None:
        ntodo = len(self._ready)
        for i in range(ntodo):
            handle = self._ready.popleft()
            if handle._cancelled:
                continue
            handle._run()
            if self._decision_failure is not None:
                return

        # Poll waiters; only stop early if settling one schedules new work,
        # so remaining waiters are not skipped.
        i = 0
        while i < len(self._waiters):
            w = self._waiters[i]
            ready_before = len(self._ready)
            settled = w.poll()
            if self._decision_failure is not None:
                return
            if settled:
                del self._waiters[i]
                if len(self._ready) > ready_before:
                    return
            else:
                i += 1

    def _run_forever_setup(self) -> None:
        self._check_closed()
        self._check_running()
        self._set_running()

    def _set_running(self) -> None:
        self._thread_id = threading.get_ident()
        events._set_running_loop(self)

    def _run_forever_cleanup(self) -> None:
        self._stopping = False
        self._thread_id = None
        events._set_running_loop(None)

    def stop(self) -> None:
        self._stopping = True

    def _check_closed(self) -> None:
        if self._closed:
            raise self._abort_error()

    def _check_running(self) -> None:
        if self.is_running():
            raise RuntimeError("This event loop is already running")
        if events._get_running_loop() is not None:
            raise RuntimeError(
                "Cannot run the event loop while another loop is running"
            )

    def is_running(self) -> bool:
        return self._thread_id is not None

    def close(self) -> None:
        """Close the loop and unwind every pending coroutine.

        The event loop must not be running. Coroutines are unwound directly rather
        than by running the loop, so each finally block runs once and no other
        workflow code is scheduled. Once closed, interacting with the loop raises
        DecisionAbortedError.
        """
        if self.is_running():
            raise RuntimeError("Cannot close a running event loop")
        if self._closed:
            return
        if self._debug:
            logger.debug("Close %r", self)
        self._check_running()
        self._closed = True
        # Mark the loop as running so get_running_loop() works in finally blocks.
        self._set_running()
        try:
            # create_task() refuses new tasks once the loop is closed, so finally
            # blocks can't add to this snapshot.
            for task in reversed(list(self._tasks.values())):
                task.destroy(self._abort_error)
        finally:
            self._run_forever_cleanup()
            # Callbacks scheduled while unwinding are dropped on purpose: every
            # task they would wake has already been unwound.
            self._ready.clear()
            self._waiters.clear()

    def is_closed(self) -> bool:
        """Returns True if the event loop was closed."""
        return self._closed

    # Timer operations - not supported for deterministic execution
    def time(self) -> float:
        raise NotImplementedError("Timers not supported in deterministic event loop")

    def call_later(  # type: ignore[override]
        self,
        delay: float,
        callback: Callable[..., Any],
        *args: Any,
        context: Context | None = None,
    ) -> TimerHandle:
        raise NotImplementedError("Timers not supported in deterministic event loop")

    def call_at(  # type: ignore[override]
        self,
        when: float,
        callback: Callable[..., Any],
        *args: Any,
        context: Context | None = None,
    ) -> TimerHandle:
        raise NotImplementedError("Timers not supported in deterministic event loop")

    # Thread operations - not supported
    def call_soon_threadsafe(  # type: ignore[override]
        self, callback: Callable[..., Any], *args: Any, context: Context | None = None
    ) -> Handle:
        raise NotImplementedError(
            "Thread operations not supported in deterministic event loop"
        )

    def run_in_executor(  # type: ignore[override]
        self, executor: Any, func: Callable[..., Any], *args: Any
    ) -> Future[Any]:
        raise NotImplementedError(
            "Executor operations not supported in deterministic event loop"
        )

    def set_default_executor(self, executor: Any) -> None:
        raise NotImplementedError(
            "Executor operations not supported in deterministic event loop"
        )

    # I/O operations - not supported for deterministic execution
    def add_reader(self, fd: int, callback: Callable[..., Any], *args: Any) -> None:  # type: ignore[override]
        raise NotImplementedError(
            "I/O operations not supported in deterministic event loop"
        )

    def remove_reader(self, fd: int) -> bool:  # type: ignore[override]
        raise NotImplementedError(
            "I/O operations not supported in deterministic event loop"
        )

    def add_writer(self, fd: int, callback: Callable[..., Any], *args: Any) -> None:  # type: ignore[override]
        raise NotImplementedError(
            "I/O operations not supported in deterministic event loop"
        )

    def remove_writer(self, fd: int) -> bool:  # type: ignore[override]
        raise NotImplementedError(
            "I/O operations not supported in deterministic event loop"
        )

    # Socket operations - not supported
    async def sock_recv(self, sock: Any, nbytes: int) -> bytes:
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    async def sock_recv_into(self, sock: Any, buf: Any) -> int:
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    async def sock_sendall(self, sock: Any, data: bytes) -> None:  # type: ignore[override]
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    async def sock_connect(self, sock: Any, address: Any) -> None:
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    async def sock_accept(self, sock: Any) -> tuple[Any, Any]:
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    async def sock_sendfile(  # type: ignore[override]
        self,
        sock: Any,
        file: Any,
        offset: int = 0,
        count: int | None = None,
        *,
        fallback: bool = True,
    ) -> int:
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    async def sock_recvfrom(self, sock: Any, bufsize: int) -> tuple[bytes, Any]:
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    async def sock_recvfrom_into(
        self, sock: Any, buf: Any, nbytes: int = 0
    ) -> tuple[int, Any]:
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    async def sock_sendto(self, sock: Any, data: bytes, address: Any) -> int:  # type: ignore[override]
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )

    # DNS operations - not supported
    async def getaddrinfo(  # type: ignore[override]
        self,
        host: str | None,
        port: int | str | None,
        *,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[Any, ...]]:
        raise NotImplementedError(
            "DNS operations not supported in deterministic event loop"
        )

    async def getnameinfo(  # type: ignore[override]
        self, sockaddr: tuple[str, int], flags: int = 0
    ) -> tuple[str, str]:
        raise NotImplementedError(
            "DNS operations not supported in deterministic event loop"
        )

    # Network connection operations - not supported
    async def create_connection(
        self,
        protocol_factory: Any,
        host: str | None = None,
        port: int | None = None,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        raise NotImplementedError(
            "Network operations not supported in deterministic event loop"
        )

    async def create_server(  # type: ignore[override]
        self,
        protocol_factory: Any,
        host: str | None = None,
        port: int | None = None,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError(
            "Network operations not supported in deterministic event loop"
        )

    async def create_unix_connection(
        self, protocol_factory: Any, path: str | None = None, **kwargs: Any
    ) -> tuple[Any, Any]:
        raise NotImplementedError(
            "Unix socket operations not supported in deterministic event loop"
        )

    async def create_unix_server(  # type: ignore[override]
        self, protocol_factory: Any, path: str | None = None, **kwargs: Any
    ) -> Any:
        raise NotImplementedError(
            "Unix socket operations not supported in deterministic event loop"
        )

    async def create_datagram_endpoint(  # type: ignore[override]
        self,
        protocol_factory: Any,
        local_addr: tuple[str, int] | None = None,
        remote_addr: tuple[str, int] | None = None,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        raise NotImplementedError(
            "Datagram operations not supported in deterministic event loop"
        )

    async def sendfile(
        self,
        transport: Any,
        file: Any,
        offset: int = 0,
        count: int | None = None,
        *,
        fallback: bool = True,
    ) -> int:
        raise NotImplementedError(
            "Sendfile operations not supported in deterministic event loop"
        )

    async def start_tls(
        self, transport: Any, protocol: Any, sslcontext: Any, **kwargs: Any
    ) -> Any:
        raise NotImplementedError(
            "TLS operations not supported in deterministic event loop"
        )

    # Pipe operations - not supported
    async def connect_read_pipe(
        self, protocol_factory: Any, pipe: Any
    ) -> tuple[Any, Any]:
        raise NotImplementedError(
            "Pipe operations not supported in deterministic event loop"
        )

    async def connect_write_pipe(
        self, protocol_factory: Any, pipe: Any
    ) -> tuple[Any, Any]:
        raise NotImplementedError(
            "Pipe operations not supported in deterministic event loop"
        )

    # Subprocess operations - not supported
    async def subprocess_shell(self, cmd: str, **kwargs: Any) -> Any:  # type: ignore[override]
        raise NotImplementedError(
            "Subprocess operations not supported in deterministic event loop"
        )

    async def subprocess_exec(self, program: str, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise NotImplementedError(
            "Subprocess operations not supported in deterministic event loop"
        )

    # Signal handlers - not supported
    def add_signal_handler(  # type: ignore[override]
        self, sig: int, callback: Callable[..., Any], *args: Any
    ) -> None:
        raise NotImplementedError(
            "Signal handlers not supported in deterministic event loop"
        )

    def remove_signal_handler(self, sig: int) -> bool:
        raise NotImplementedError(
            "Signal handlers not supported in deterministic event loop"
        )

    # Exception handling
    def set_exception_handler(
        self, handler: Callable[[Any, dict[str, Any]], Any] | None
    ) -> None:
        raise NotImplementedError(
            "Custom exception handlers not supported in deterministic event loop"
        )

    def get_exception_handler(self) -> Callable[[Any, dict[str, Any]], Any] | None:
        raise NotImplementedError(
            "Custom exception handlers not supported in deterministic event loop"
        )

    def default_exception_handler(self, context: dict[str, Any]) -> None:
        raise NotImplementedError(
            "Custom exception handlers not supported in deterministic event loop"
        )

    def call_exception_handler(self, context: dict[str, Any]) -> None:
        message = context.get("message")
        if not message:
            message = "Unhandled exception in event loop"

        exception = context.get("exception")

        if isinstance(exception, BaseException):
            exc_info = exception
        else:
            exc_info = None

        log_lines = [message]
        for key in sorted(context):
            if key in {"message", "exception"}:
                continue
            value = context[key]
            if key == "source_traceback":
                tb = "".join(traceback.format_list(value))
                value = "Object created at (most recent call last):\n"
                value += tb.rstrip()
            elif key == "handle_traceback":
                tb = "".join(traceback.format_list(value))
                value = "Handle created at (most recent call last):\n"
                value += tb.rstrip()
            else:
                value = repr(value)
            log_lines.append(f"{key}: {value}")

        logger.error("\n".join(log_lines), exc_info=exc_info)

    # Task factory
    def set_task_factory(  # type: ignore[override]
        self, factory: Callable[[Any, Coroutine[Any, Any, Any]], Task[Any]] | None
    ) -> None:
        raise NotImplementedError(
            "Custom task factory not supported in deterministic event loop"
        )

    def get_task_factory(  # type: ignore[override]
        self,
    ) -> Callable[[Any, Coroutine[Any, Any, Any]], Task[Any]] | None:
        return None

    # Shutdown operations
    async def shutdown_asyncgens(self) -> None:
        # This is a no-op for deterministic event loop
        pass

    async def shutdown_default_executor(self, timeout: float | None = None) -> None:
        # This is a no-op for deterministic event loop
        pass

    # Accepted socket connection
    async def connect_accepted_socket(
        self, protocol_factory: Any, sock: Any, **kwargs: Any
    ) -> tuple[Any, Any]:
        raise NotImplementedError(
            "Socket operations not supported in deterministic event loop"
        )


# Bounds how long workflow code that keeps catching the error can delay close().
_MAX_DESTROY_THROWS = 100


class _DeterministicTask(Task[_T]):
    """A Task that keeps its Context so close() can unwind it in that Context."""

    def __init__(
        self,
        coro: Generator[Any, None, _T] | Coroutine[Any, Any, _T],
        *,
        loop: AbstractEventLoop,
        name: str | None = None,
        context: Context | None = None,
    ) -> None:
        if context is None:
            context = copy_context()
        super().__init__(coro, loop=loop, name=name, context=context)
        self._destroy_context = context
        # close() unwinds coroutines directly, so tasks are never marked done.
        # Disable the "Task was destroyed but it is pending!" log for them.
        if hasattr(self, "_log_destroy_pending"):
            setattr(self, "_log_destroy_pending", False)

    def destroy(self, abort_error: Callable[[], DecisionAbortedError]) -> None:
        if self.done():
            if isinstance(getattr(self, "_exception", None), FatalDecisionError):
                # Already surfaced as the decision failure, don't log it again
                # as "Task exception was never retrieved". Other exceptions are
                # left alone so unretrieved user errors are still reported.
                self._log_traceback = False
            return
        coro = self.get_coro()
        if not inspect.iscoroutine(coro):
            return
        state = inspect.getcoroutinestate(coro)
        if state == inspect.CORO_CREATED:
            # Never started: closing runs no workflow code.
            coro.close()
            return
        if state != inspect.CORO_SUSPENDED:
            return
        # Each async context manager whose __aexit__ awaits (e.g. a TaskGroup waiting on
        # its children) yields once while handling the error, so throw again at each new
        # await point until the coroutine finishes. close() can't do this: awaiting while
        # handling GeneratorExit fails and leaves the coroutine for the garbage collector.
        for _ in range(_MAX_DESTROY_THROWS):
            try:
                self._destroy_context.run(coro.throw, abort_error())
            except (StopIteration, FatalDecisionError):
                return
            except BaseExceptionGroup as e:
                if e.split(FatalDecisionError)[1] is not None:
                    logger.warning(
                        "Workflow code raised while being destroyed", exc_info=True
                    )
                return
            except (Exception, CancelledError):
                logger.warning(
                    "Workflow code raised while being destroyed", exc_info=True
                )
                return
        try:
            self._destroy_context.run(coro.close)
        except (Exception, CancelledError):
            logger.error(
                "Workflow coroutine could not be destroyed, it will be finalized by "
                "the garbage collector",
                exc_info=True,
            )


def _run_until_complete_cb(fut: Future[Any]) -> None:
    if not fut.cancelled():
        exc = fut.exception()
        if isinstance(exc, (SystemExit, KeyboardInterrupt)):
            return
    fut.get_loop().stop()
