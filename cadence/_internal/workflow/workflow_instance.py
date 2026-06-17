import inspect
import logging
from asyncio import Task
from typing import Any, Optional, Callable, Awaitable

from cadence._internal.workflow.deterministic_event_loop import (
    DeterministicEventLoop,
)
from cadence.error import SignalFailure
from cadence.query import QueryDefinition
from cadence.signal import SignalDefinition
from cadence.workflow import WorkflowCancellationInfo, WorkflowDefinition

logger = logging.getLogger(__name__)


class WorkflowInstance:
    """Runs a workflow object on the deterministic event loop.

    Operates entirely on decoded Python values: callers (the engine) own the
    :class:`DataConverter` and are responsible for decoding inputs before they
    reach this class and encoding results after they leave it.
    """

    def __init__(
        self,
        loop: DeterministicEventLoop,
        definition: WorkflowDefinition[Any],
    ):
        self._loop = loop
        self._definition = definition
        self._instance = definition.cls()  # construct a new workflow object
        self._task: Optional[Task[Any]] = None
        # Strong references to in-flight async signal handler tasks.
        self._signal_tasks: set[Task[Any]] = set()
        # Fail the decision task if a signal handler raises an exception.
        self._signal_failure: Optional[SignalFailure] = None

    def get_signal_failure(self) -> Optional[SignalFailure]:
        return self._signal_failure

    def start(self, args: list[Any]) -> None:
        if self._task is None:
            run_method = self._definition.get_run_method(self._instance)
            self._task = self._loop.create_task(self._run(run_method, args))

    def request_cancel(self, info: WorkflowCancellationInfo) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel(info.cause)

    async def _run(
        self, workflow_fn: Callable[..., Awaitable[Any]], args: list[Any]
    ) -> Any:
        return await workflow_fn(*args)

    def run_until_yield(self):
        self._loop.run_until_yield()

    def is_done(self) -> bool:
        return self._task is not None and self._task.done()

    def get_result(self) -> Any:
        """Return the workflow's decoded result, or None if not yet done.

        Re-raises any exception the workflow run method raised.
        """
        if self._task is None or not self._task.done():
            return None
        return self._task.result()

    def handle_signal(
        self, signal_def: SignalDefinition[..., Any], args: list[Any]
    ) -> None:
        task = self._loop.create_task(self._run_signal(signal_def, args))
        self._signal_tasks.add(task)
        task.add_done_callback(
            lambda completed_task: self._on_signal_task_done(
                completed_task, signal_def.name
            )
        )

    async def _run_signal(
        self, signal_def: SignalDefinition[..., Any], args: list[Any]
    ) -> None:
        result = signal_def(self._instance, *args)
        if inspect.iscoroutine(result):
            await result

    def handle_query(
        self, query_def: QueryDefinition[..., Any], args: list[Any]
    ) -> Any:
        """Execute a query handler and return its decoded result.

        The query runs synchronously against the current workflow state
        (after replay has caught up). It must not mutate state.

        Args:
            query_def: The registered query definition.
            args: Decoded query arguments.

        Returns:
            The query handler's result (not serialized).

        Raises:
            TypeError: If the query handler is asynchronous.
            Exception: If the query handler raises.
        """
        result = query_def(self._instance, *args)
        if inspect.iscoroutine(result):
            result.close()
            raise TypeError(
                f"Query handler '{query_def.name}' must be synchronous, "
                f"got async function"
            )
        return result

    def _on_signal_task_done(self, task: Task[Any], signal_name: str) -> None:
        self._signal_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if isinstance(exc, Exception) and self._signal_failure is None:
            self._signal_failure = SignalFailure(str(exc) or None, signal_name)
