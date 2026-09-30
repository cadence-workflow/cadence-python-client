from cadence import Registry, workflow

from tests.integration_tests.canary.constants import (
    WORKFLOW_TYPE_RESET,
    WORKFLOW_TYPE_RESET_BASE,
)
from tests.integration_tests.canary.unsupported import raise_unsupported

reset_registry = Registry()


@reset_registry.workflow(name=WORKFLOW_TYPE_RESET)
class ResetWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise_unsupported(WORKFLOW_TYPE_RESET)


@reset_registry.workflow(name=WORKFLOW_TYPE_RESET_BASE)
class ResetBaseWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise_unsupported(WORKFLOW_TYPE_RESET_BASE)
