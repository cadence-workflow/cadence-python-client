import asyncio
from typing import Any

from cadence._internal.workflow.statemachine.decision_state_machine import (
    CancelFn,
    ConverterFn,
    DecisionFuture,
)
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.workflow import (
    ChildWorkflowFuture,
    ResultType,
    WorkflowContext,
    WorkflowFuture,
)


class ChildWorkflowFutureImpl(
    DecisionFuture[ResultType], ChildWorkflowFuture[ResultType]
):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        request_cancel: CancelFn | None = None,
        converter: ConverterFn[ResultType] | None = None,
        *,
        workflow_id: str,
        execution: WorkflowFuture[WorkflowExecution],
    ) -> None:
        super().__init__(loop, request_cancel, converter)
        self._workflow_id = workflow_id
        self._execution = execution

    @property
    def workflow_id(self) -> str:
        return self._workflow_id

    @property
    def execution(self) -> WorkflowFuture[WorkflowExecution]:
        return self._execution

    def signal(self, signal_name: str, *args: Any) -> WorkflowFuture[None]:
        """Send a signal to this child workflow."""
        return WorkflowContext.get().signal_child_workflow(
            self._workflow_id, signal_name, *args
        )
