import asyncio
from datetime import timedelta

from cadence import Registry, activity, workflow

from tests.canary.constants import (
    ACTIVITY_TYPE_RETRY_ON_FAILURE,
    ACTIVITY_TYPE_RETRY_ON_TIMEOUT,
    WORKFLOW_TYPE_RETRY,
)

_RETRY_POLICY: workflow.RetryPolicy = {
    "initial_interval": timedelta(seconds=1),
    "backoff_coefficient": 1.0,
    "maximum_interval": timedelta(seconds=1),
    "maximum_attempts": 5,
}

retry_registry = Registry()


@retry_registry.activity(name=ACTIVITY_TYPE_RETRY_ON_TIMEOUT)
async def retry_on_timeout_activity() -> int:
    attempt = activity.info().attempt
    if attempt < 2:
        await asyncio.sleep(2)
    return attempt * 100


@retry_registry.activity(name=ACTIVITY_TYPE_RETRY_ON_FAILURE)
async def retry_on_failure_activity() -> int:
    attempt = activity.info().attempt
    if attempt < 3:
        raise RuntimeError("retry me")
    return attempt


@retry_registry.workflow(name=WORKFLOW_TYPE_RETRY)
class RetryWorkflow:
    @workflow.run
    async def run(self) -> None:
        timeout_result, failure_result = await asyncio.gather(
            workflow.execute_activity(
                ACTIVITY_TYPE_RETRY_ON_TIMEOUT,
                int,
                schedule_to_close_timeout=timedelta(seconds=30),
                start_to_close_timeout=timedelta(seconds=1),
                retry_policy=_RETRY_POLICY,
            ),
            workflow.execute_activity(
                ACTIVITY_TYPE_RETRY_ON_FAILURE,
                int,
                schedule_to_close_timeout=timedelta(seconds=30),
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=_RETRY_POLICY,
            ),
        )
        if timeout_result < 200:
            raise ValueError(f"unexpected timeout retry result: {timeout_result}")
        if failure_result < 3:
            raise ValueError(f"unexpected failure retry result: {failure_result}")
