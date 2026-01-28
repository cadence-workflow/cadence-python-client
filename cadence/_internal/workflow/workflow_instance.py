import logging
from asyncio import Task
from typing import Any, Optional, Callable, Awaitable
from cadence._internal.workflow.deterministic_event_loop import (
    DeterministicEventLoop,
)
from cadence.api.v1.common_pb2 import Payload

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
