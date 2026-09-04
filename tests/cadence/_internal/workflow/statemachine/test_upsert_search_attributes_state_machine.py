from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionState,
)
from cadence._internal.workflow.statemachine.upsert_search_attributes_state_machine import (
    UpsertSearchAttributesStateMachine,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload, SearchAttributes


def _attrs() -> decision.UpsertWorkflowSearchAttributesDecisionAttributes:
    search = SearchAttributes()
    search.indexed_fields["CustomIntField"].CopyFrom(Payload(data=b"1"))
    return decision.UpsertWorkflowSearchAttributesDecisionAttributes(
        search_attributes=search
    )


async def test_upsert_state_machine_requested():
    attrs = _attrs()
    machine = UpsertSearchAttributesStateMachine(attrs, "0")

    assert machine.state is DecisionState.REQUESTED
    assert machine.get_decision() == decision.Decision(
        upsert_workflow_search_attributes_decision_attributes=attrs
    )


async def test_upsert_state_machine_recorded():
    attrs = _attrs()
    machine = UpsertSearchAttributesStateMachine(attrs, "0")

    machine.handle_recorded(history.UpsertWorkflowSearchAttributesEventAttributes())

    assert machine.state is DecisionState.COMPLETED
    assert machine.get_decision() is None


async def test_upsert_state_machine_not_cancellable():
    attrs = _attrs()
    machine = UpsertSearchAttributesStateMachine(attrs, "0")

    assert machine.request_cancel() is False
    assert machine.get_decision() == decision.Decision(
        upsert_workflow_search_attributes_decision_attributes=attrs
    )
