from asyncio import CancelledError, InvalidStateError, Task
from typing import Optional
from cadence._internal.workflow.deterministic_event_loop import DeterministicEventLoop
from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DataConverter
from cadence.error import WorkflowFailure
from cadence.workflow import WorkflowDefinition


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
        self._task: Optional[Task] = None

    def start(self, payload: Payload):
        if self._task is None:
            run_method = self._definition.get_run_method(self._instance)
            # noinspection PyProtectedMember
            workflow_input = self._definition._run_signature.params_from_payload(
                self._data_converter, payload
            )
            self._task = self._loop.create_task(run_method(*workflow_input))

    def run_once(self):
        self._loop.run_until_yield()

    def is_done(self) -> bool:
        return self._task is not None and self._task.done()

    # TODO: consider cache result to avoid multiple data conversions
    def get_result(self) -> Payload:
        if self._task is None:
            raise RuntimeError("Workflow is not started yet")
        try:
            result = self._task.result()
        except (CancelledError, InvalidStateError) as e:
            raise e
        except Exception as e:
            raise WorkflowFailure(f"Workflow failed: {e}") from e
        # TODO: handle result with multiple outputs
        return self._data_converter.to_data([result])
