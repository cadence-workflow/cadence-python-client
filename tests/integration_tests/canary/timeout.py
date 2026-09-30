import asyncio
from datetime import timedelta

from cadence import Registry, workflow
from cadence.error import ActivityFailure

from tests.integration_tests.canary.constants import (
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
            if "TIMEOUT_TYPE_START_TO_CLOSE" not in str(error):
                raise
        else:
            raise RuntimeError("expected activity to time out")
