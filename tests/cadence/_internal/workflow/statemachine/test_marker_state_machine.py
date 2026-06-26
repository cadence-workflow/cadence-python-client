from cadence._internal.workflow.statemachine.marker_state_machine import (
    MarkerStateMachine,
    attach_marker_id,
    marker_id_from_attrs,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Header, Payload


async def test_marker_state_machine_requested():
    attrs = decision.RecordMarkerDecisionAttributes(marker_name="SideEffect")
    machine = MarkerStateMachine(attrs, "marker-1")

    assert machine.get_decision() == decision.Decision(
        record_marker_decision_attributes=attrs
    )


async def test_marker_state_machine_recorded():
    attrs = decision.RecordMarkerDecisionAttributes(marker_name="SideEffect")
    machine = MarkerStateMachine(attrs, "marker-1")

    machine.handle_recorded(
        history.MarkerRecordedEventAttributes(
            marker_name="SideEffect", details=Payload(data=b"recorded")
        )
    )

    assert machine.get_decision() is None


async def test_marker_state_machine_not_cancellable():
    attrs = decision.RecordMarkerDecisionAttributes(marker_name="SideEffect")
    machine = MarkerStateMachine(attrs, "marker-1")

    assert machine.request_cancel() is False
    assert machine.get_decision() == decision.Decision(
        record_marker_decision_attributes=attrs
    )


async def test_marker_state_machine_preserves_details_and_header():
    attrs = decision.RecordMarkerDecisionAttributes(
        marker_name="SideEffect",
        details=Payload(data=b"payload"),
        header=Header(fields={"key": Payload(data=b"value")}),
    )
    machine = MarkerStateMachine(attrs, "marker-1")

    emitted = machine.get_decision()

    assert emitted == decision.Decision(record_marker_decision_attributes=attrs)
    assert emitted.record_marker_decision_attributes.details == Payload(data=b"payload")
    assert emitted.record_marker_decision_attributes.header == Header(
        fields={"key": Payload(data=b"value")}
    )


async def test_attach_marker_id_preserves_existing_header_fields():
    attrs = decision.RecordMarkerDecisionAttributes(
        marker_name="SideEffect",
        header=Header(fields={"key": Payload(data=b"value")}),
    )

    attach_marker_id(attrs, "marker-1")

    assert marker_id_from_attrs(attrs) == "marker-1"
    assert attrs.header.fields["key"] == Payload(data=b"value")
