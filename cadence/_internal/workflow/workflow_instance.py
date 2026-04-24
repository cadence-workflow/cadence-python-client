import inspect
import logging
from asyncio import Task
from typing import Any, Optional, Callable, Awaitable

from cadence._internal.workflow.deterministic_event_loop import (
    DeterministicEventLoop,
)
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.history_pb2 import (
    HistoryEvent,
    WorkflowExecutionSignaledEventAttributes,
)

from cadence.data_converter import DataConverter
from cadence.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)


class WorkflowInstance:
    def __init__(
        self,
        loop: DeterministicEventLoop,
        workflow_definition: WorkflowDefinition,
        data_converter: DataConverter,
    ):
        self._loop = loop
        self._definition = workflow_definition
        self._data_converter = data_converter
        self._instance = workflow_definition.cls()  # construct a new workflow object
        self._task: Optional[Task[Payload]] = None
        # Strong references to in-flight async signal handler tasks.
        self._signal_tasks: set[Task[Any]] = set()

    def start(self, payload: Payload):
        if self._task is None:
            run_method = self._definition.get_run_method(self._instance)
            # noinspection PyProtectedMember
            workflow_input = self._definition._run_signature.params_from_payload(
                self._data_converter, payload
            )

            self._task = self._loop.create_task(self._run(run_method, workflow_input))

    async def _run(
        self, workflow_fn: Callable[[Any], Awaitable[Any]], args: list[Any]
    ) -> Payload:
        result = await workflow_fn(*args)
        return self._data_converter.to_data([result])

    def run_until_yield(self):
        self._loop.run_until_yield()

    def is_done(self) -> bool:
        return self._task is not None and self._task.done()

    def get_result(self) -> Optional[Payload]:
        if self._task is None or not self._task.done():
            return None
        return self._task.result()

    def handle_signal_event(self, event: HistoryEvent) -> None:
        attrs = event.workflow_execution_signaled_event_attributes
        self.handle_signal_attributes(attrs)

    def handle_signal_attributes(
        self, attrs: WorkflowExecutionSignaledEventAttributes
    ) -> None:
        self._loop.call_soon(self._invoke_signal, attrs.signal_name, attrs.input)

    def _invoke_signal(self, signal_name: str, payload: Payload) -> None:
        signal_def = self._definition.signals.get(signal_name)
        if signal_def is None:
            logger.warning(
                "Received signal '%s' but no handler registered, dropping",
                signal_name,
            )
            return

        try:
            args = signal_def.params_from_payload(self._data_converter, payload)
        except Exception as e:
            logger.warning(
                "Failed to decode payload for signal '%s', dropping: %s",
                signal_name,
                e,
            )
            return

        result = signal_def(self._instance, *args)

        # Async handlers return a coroutine; wrap it in a deterministic-loop
        # task and hold a strong reference until it finishes so asyncio does
        # not collect it mid-flight.
        if inspect.iscoroutine(result):
            task = self._loop.create_task(result)
            self._signal_tasks.add(task)
            task.add_done_callback(self._on_signal_task_done)

    def _on_signal_task_done(self, task: Task[Any]) -> None:
        self._signal_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if isinstance(exc, Exception):
            raise exc
