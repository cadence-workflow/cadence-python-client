from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionStateMachine,
    DecisionId,
    DecisionType,
)
from cadence.api.v1 import decision

COMPLETE = "complete"

COMPLETION_ID = DecisionId(DecisionType.WORKFLOW_COMPLETE, COMPLETE)


class CompletionStateMachine(DecisionStateMachine):
    def __init__(self, outcome: decision.Decision) -> None:
        super().__init__()
        self.outcome = outcome

    def get_id(self) -> DecisionId:
        return COMPLETION_ID

    def get_decision(self) -> decision.Decision | None:
        return self.outcome

    def request_cancel(self) -> bool:
        return False
