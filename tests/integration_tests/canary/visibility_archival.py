from cadence import Registry, workflow

from tests.integration_tests.canary.constants import WORKFLOW_TYPE_VISIBILITY_ARCHIVAL
from tests.integration_tests.canary.unsupported import raise_unsupported

visibility_archival_registry = Registry()


@visibility_archival_registry.workflow(name=WORKFLOW_TYPE_VISIBILITY_ARCHIVAL)
class VisibilityArchivalWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise_unsupported(WORKFLOW_TYPE_VISIBILITY_ARCHIVAL)
