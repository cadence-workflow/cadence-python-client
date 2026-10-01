from cadence import Registry, workflow

from tests.canary.constants import WORKFLOW_TYPE_SEARCH_ATTRIBUTES
from tests.canary.unsupported import raise_unsupported

search_attributes_registry = Registry()


@search_attributes_registry.workflow(name=WORKFLOW_TYPE_SEARCH_ATTRIBUTES)
class SearchAttributesWorkflow:
    @workflow.run
    async def run(self) -> None:
        raise_unsupported(WORKFLOW_TYPE_SEARCH_ATTRIBUTES)
