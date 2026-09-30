from cadence import Registry, workflow

from tests.integration_tests.canary.constants import WORKFLOW_TYPE_VISIBILITY
from tests.integration_tests.canary.unsupported import raise_unsupported

visibility_registry = Registry()


@visibility_registry.workflow(name=WORKFLOW_TYPE_VISIBILITY)
class VisibilityWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise_unsupported(WORKFLOW_TYPE_VISIBILITY)
