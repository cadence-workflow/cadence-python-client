import asyncio
from datetime import timedelta

from cadence import Registry, workflow
from cadence.error import ActivityFailure

from tests.canary.constants import (
    ACTIVITY_TYPE_TIMEOUT,
    WORKFLOW_TYPE_TIMEOUT,
)

timeout_registry = Registry()


@timeout_registry.activity(name=ACTIVITY_TYPE_TIMEOUT)
async def timeout_activity() -> None:
    await asyncio.sleep(4)


@timeout_registry.workflow(name=WORKFLOW_TYPE_TIMEOUT)
class TimeoutWorkflow:
    @workflow.run
    async def run(self) -> None:
        try:
            await workflow.execute_activity(
                ACTIVITY_TYPE_TIMEOUT,
                type(None),
                schedule_to_close_timeout=timedelta(seconds=2),
                schedule_to_start_timeout=timedelta(seconds=1),
                start_to_close_timeout=timedelta(seconds=1),
            )
        except ActivityFailure as error:
            if not str(error).startswith("TIMEOUT_TYPE_"):
                raise
        else:
            raise RuntimeError("expected activity to time out")
