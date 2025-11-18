from cadence.workflow import WorkflowDefinition


class WorkflowInstance:
    def __init__(self, workflow_definition: WorkflowDefinition):
        self._definition = workflow_definition
        self._instance = workflow_definition.cls().__init__()

    async def run(self, *args):
        run_method = self._definition.get_run_method(self._instance)
        return run_method(*args)
