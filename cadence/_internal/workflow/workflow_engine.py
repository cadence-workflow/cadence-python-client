from dataclasses import dataclass

from cadence._internal.workflow.context import Context
from cadence.api.v1.decision_pb2 import Decision
from cadence.client import Client
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.workflow import WorkflowInfo


@dataclass
class DecisionResult:
    decisions: list[Decision]

class WorkflowEngine:
    def __init__(self, info: WorkflowInfo, client: Client):
        self._context = Context(client, info)

    # TODO: Implement this
    def process_decision(self, decision_task: PollForDecisionTaskResponse) -> DecisionResult:
        with self._context._activate():
            return DecisionResult(decisions=[])
