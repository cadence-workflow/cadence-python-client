import asyncio
from datetime import timedelta

from cadence import Registry, workflow
from cadence.error import ChildWorkflowExecutionCanceled
from cadence.workflow import WorkflowContext

from tests.canary.constants import (
    CHILD_WORKFLOW_TIMEOUT,
    WORKFLOW_TYPE_CANCELLATION,
    WORKFLOW_TYPE_CANCELLATION_EXTERNAL,
)

cancellation_registry = Registry()


@cancellation_registry.workflow(name=WORKFLOW_TYPE_CANCELLATION_EXTERNAL)
class CancellationExternalWorkflow:
    @workflow.run
    async def run(self) -> str:
        await workflow.sleep(timedelta(seconds=10))
        return "not cancelled"


@cancellation_registry.workflow(name=WORKFLOW_TYPE_CANCELLATION)
class CancellationWorkflow:
    @workflow.run
    async def run(self) -> None:
        parent_id = WorkflowContext.get().info().workflow_id
        handle = await workflow.start_child_workflow(
            WORKFLOW_TYPE_CANCELLATION_EXTERNAL,
            str,
            workflow_id=f"{parent_id}/cancellation-child",
            execution_start_to_close_timeout=CHILD_WORKFLOW_TIMEOUT,
        )

        await workflow.sleep(timedelta(seconds=1))
        handle.cancel()

        try:
            await handle
        except (asyncio.CancelledError, ChildWorkflowExecutionCanceled):
            return
        raise RuntimeError("child workflow completed without being cancelled")
