import asyncio
from datetime import timedelta

from cadence import Registry, workflow
from cadence.error import ActivityError, CadenceTimeoutError

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
        except ActivityError as error:
            if not isinstance(error.cause, CadenceTimeoutError):
                raise
        else:
            raise RuntimeError("expected activity to time out")
