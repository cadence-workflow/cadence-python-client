from dataclasses import dataclass
from typing import Optional, Callable, Any

from cadence._internal.workflow.context import Context
from cadence.api.v1.decision_pb2 import Decision
from cadence.client import Client
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.workflow import WorkflowInfo


@dataclass
class DecisionResult:
    decisions: list[Decision]
    force_create_new_decision_task: bool = False
    query_results: Optional[dict] = None

class WorkflowEngine:
    def __init__(self, info: WorkflowInfo, client: Client, workflow_func: Optional[Callable[..., Any]] = None):
        self._context = Context(client, info)
        self._workflow_func = workflow_func

    # TODO: Implement this
    async def process_decision(self, decision_task: PollForDecisionTaskResponse) -> DecisionResult:
        with self._context._activate():
            return DecisionResult(decisions=[])
