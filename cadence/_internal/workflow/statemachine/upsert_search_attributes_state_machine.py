from cadence._internal.workflow.statemachine.decision_state_machine import (
    BaseDecisionStateMachine,
    DecisionId,
    DecisionState,
    DecisionType,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence.api.v1 import decision, history

upsert_search_attributes_events = EventDispatcher()


class UpsertSearchAttributesStateMachine(BaseDecisionStateMachine):
    """State machine for UpsertWorkflowSearchAttributes decisions.

    History events do not carry a client-generated ID, so DecisionManager
    matches recorded events to REQUESTED machines in insertion order.
    """

    request: decision.UpsertWorkflowSearchAttributesDecisionAttributes
    _upsert_id: str

    def __init__(
        self,
        request: decision.UpsertWorkflowSearchAttributesDecisionAttributes,
        upsert_id: str,
    ) -> None:
        super().__init__()
        self.request = request
        self._upsert_id = upsert_id

    def get_id(self) -> DecisionId:
        return DecisionId(DecisionType.UPSERT_SEARCH_ATTRIBUTES, self._upsert_id)

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(
                upsert_workflow_search_attributes_decision_attributes=self.request
            )
        return None

    def request_cancel(self, message: str | None = None) -> bool:
        return False

    @upsert_search_attributes_events.event()
    def handle_recorded(
        self, _: history.UpsertWorkflowSearchAttributesEventAttributes
    ) -> None:
        self._transition(DecisionState.COMPLETED)
