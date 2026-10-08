import asyncio
from typing import Any, Awaitable, Generator, Type, cast

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DataConverter
from cadence.workflow import ResultType, WorkflowContext


class ChildWorkflowFutureImpl(Awaitable[ResultType]):
    def __init__(
        self,
        workflow_id: str,
        run_id: str,
        result_future: "asyncio.Future[Payload]",
        result_type: Type[ResultType],
        data_converter: DataConverter,
    ) -> None:
        self._workflow_id = workflow_id
        self._run_id = run_id
        self._result_future = result_future
        self._result_type = result_type
        self._data_converter = data_converter

    @property
    def workflow_id(self) -> str:
        return self._workflow_id

    @property
    def run_id(self) -> str:
        return self._run_id

    def cancel(self) -> bool:
        """Request cancellation of the child workflow."""
        return self._result_future.cancel()

    async def signal(self, signal_name: str, *args: Any) -> None:
        """Send a signal to this child workflow."""
        ctx = WorkflowContext.get()
        await ctx.signal_child_workflow(self._workflow_id, signal_name, *args)

    def __await__(self) -> Generator[Any, None, ResultType]:
        payload: Payload = yield from self._result_future.__await__()
        result = self._data_converter.from_data(payload, [self._result_type])[0]
        return cast(ResultType, result)
