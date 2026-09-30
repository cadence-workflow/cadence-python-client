import asyncio
from typing import Any

from cadence import Registry, workflow
from cadence.workflow import WorkflowContext

from tests.integration_tests.canary.constants import (
    CHILD_WORKFLOW_TIMEOUT,
    DEFAULT_SANITY_CHILD_WORKFLOWS,
    WORKFLOW_TYPE_SANITY,
)

sanity_registry = Registry()


@sanity_registry.workflow(name=WORKFLOW_TYPE_SANITY)
class SanityWorkflow:
    @workflow.run
    async def run(self) -> None:
        workflow_id = WorkflowContext.get().info().workflow_id
        child_workflows = workflow.side_effect(
            lambda: list(DEFAULT_SANITY_CHILD_WORKFLOWS), list[str]
        )

        results = await asyncio.gather(
            *(
                workflow.execute_child_workflow(
                    child_workflow,
                    Any,
                    workflow_id=f"{workflow_id}/{child_workflow}",
                    execution_start_to_close_timeout=CHILD_WORKFLOW_TIMEOUT,
                )
                for child_workflow in child_workflows
            ),
            return_exceptions=True,
        )
        failures = [
            (
                child_workflow,
                result,
            )
            for child_workflow, result in zip(
                child_workflows,
                results,
                strict=True,
            )
            if isinstance(result, BaseException)
        ]
        if failures:
            details = "; ".join(
                f"{child_workflow}: {type(error).__name__}: {error}"
                for child_workflow, error in failures
            )
            raise RuntimeError(f"sanity child workflows failed: {details}")
