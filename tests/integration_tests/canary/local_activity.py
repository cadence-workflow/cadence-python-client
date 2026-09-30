from cadence import Registry, workflow

from tests.integration_tests.canary.constants import WORKFLOW_TYPE_LOCAL_ACTIVITY
from tests.integration_tests.canary.unsupported import raise_unsupported

local_activity_registry = Registry()


@local_activity_registry.workflow(name=WORKFLOW_TYPE_LOCAL_ACTIVITY)
class LocalActivityWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise_unsupported(WORKFLOW_TYPE_LOCAL_ACTIVITY)
