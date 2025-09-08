from dataclasses import dataclass
from typing import Callable

from cadence.api.v1.decision_pb2 import Decision
from cadence.client import Client
from cadence.data_converter import DataConverter
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse

@dataclass
class WorkflowContext:
    domain: str
    workflow_id: str
    run_id: str
    client: Client
    workflow_func: Callable
    data_converter: DataConverter

@dataclass
class DecisionResult:
    decisions: list[Decision]

class WorkflowEngine:
    def __init__(self, context: WorkflowContext):
        self._context = context

    # TODO: Implement this
    def process_decision(self, decision_task: PollForDecisionTaskResponse) -> DecisionResult:
        return DecisionResult(decisions=[])
