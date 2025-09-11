from cadence.client import Client
from cadence.workflow import WorkflowContext, WorkflowInfo


class Context(WorkflowContext):

    def __init__(self, client: Client, info: WorkflowInfo):
        self._client = client
        self._info = info

    def info(self) -> WorkflowInfo:
        return self._info

    def client(self) -> Client:
        return self._client
