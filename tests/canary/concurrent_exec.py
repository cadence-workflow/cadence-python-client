import asyncio

from cadence import Registry, workflow

from tests.canary.constants import (
    ACTIVITY_TIMEOUT,
    ACTIVITY_TYPE_CONCURRENT_EXECUTION,
    WORKFLOW_TYPE_CONCURRENT_EXECUTION,
)

_TOTAL_ACTIVITIES = 250

concurrent_exec_registry = Registry()


@concurrent_exec_registry.activity(name=ACTIVITY_TYPE_CONCURRENT_EXECUTION)
async def concurrent_exec_activity(index: int) -> int:
    return index


@concurrent_exec_registry.workflow(name=WORKFLOW_TYPE_CONCURRENT_EXECUTION)
class ConcurrentExecutionWorkflow:
    @workflow.run
    async def run(self) -> None:
        results = await asyncio.gather(
            *(
                workflow.execute_activity(
                    ACTIVITY_TYPE_CONCURRENT_EXECUTION,
                    int,
                    index,
                    schedule_to_close_timeout=ACTIVITY_TIMEOUT,
                )
                for index in range(_TOTAL_ACTIVITIES)
            )
        )
        if results != list(range(_TOTAL_ACTIVITIES)):
            raise ValueError("concurrent activities returned unexpected results")
