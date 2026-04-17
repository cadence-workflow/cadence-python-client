import logging
from asyncio import Task
from typing import Any, Optional, Callable, Awaitable

from cadence._internal.workflow.deterministic_event_loop import (
    DeterministicEventLoop,
)
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.history_pb2 import HistoryEvent

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
        self._signal_error: Optional[Exception] = None

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

    def check_signal_error(self) -> None:
        """Raise the first signal handler exception captured during this tick.

        Called by the engine after ``run_until_yield()`` so that user-handler
        bugs deterministically fail the decision task instead of being
        silently swallowed by the event loop's ``call_exception_handler``.
        """
        if self._signal_error is not None:
            error = self._signal_error
            self._signal_error = None
            raise error

    def handle_signal_event(
        self, event: HistoryEvent, on_applied: Callable[[], None]
    ) -> None:
        attrs = event.workflow_execution_signaled_event_attributes
        self._loop.call_soon(
            self._deliver_signal, attrs.signal_name, attrs.input, on_applied
        )

    def _deliver_signal(
        self, signal_name: str, payload: Payload, on_applied: Callable[[], None]
    ) -> None:
        """Dispatch a signal to the handler.

        ``on_applied`` is *always* called (in ``finally``) so that
        ``wait_condition`` waiters are re-evaluated regardless of handler
        success.  User-handler exceptions are stored for the engine to
        surface after ``run_until_yield``.
        """
        try:
            self._invoke_signal(signal_name, payload)
        except Exception as e:
            if self._signal_error is None:
                self._signal_error = e
        finally:
            on_applied()

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

        handler = signal_def.wrapped.__get__(self._instance)
        handler(*args)
