from cadence import Registry, workflow

from tests.integration_tests.canary.constants import (
    WORKFLOW_TYPE_ARCHIVAL_EXTERNAL,
    WORKFLOW_TYPE_HISTORY_ARCHIVAL,
)
from tests.integration_tests.canary.unsupported import raise_unsupported

history_archival_registry = Registry()


@history_archival_registry.workflow(name=WORKFLOW_TYPE_HISTORY_ARCHIVAL)
class HistoryArchivalWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise_unsupported(WORKFLOW_TYPE_HISTORY_ARCHIVAL)


@history_archival_registry.workflow(name=WORKFLOW_TYPE_ARCHIVAL_EXTERNAL)
class ArchivalExternalWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise_unsupported(WORKFLOW_TYPE_ARCHIVAL_EXTERNAL)
