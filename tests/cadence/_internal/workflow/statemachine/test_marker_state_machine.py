from cadence._internal.workflow.statemachine.marker_state_machine import (
    MarkerStateMachine,
    encode_marker_details,
    decode_marker_details,
    SIDE_EFFECT_MARKER_NAME,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Header, Payload


async def test_marker_state_machine_requested():
    attrs = decision.RecordMarkerDecisionAttributes(marker_name=SIDE_EFFECT_MARKER_NAME)
    machine = MarkerStateMachine(attrs, SIDE_EFFECT_MARKER_NAME, "0")

    assert machine.get_decision() == decision.Decision(
        record_marker_decision_attributes=attrs
    )


async def test_marker_state_machine_recorded():
    attrs = decision.RecordMarkerDecisionAttributes(marker_name=SIDE_EFFECT_MARKER_NAME)
    machine = MarkerStateMachine(attrs, SIDE_EFFECT_MARKER_NAME, "0")

    machine.handle_recorded(
        history.MarkerRecordedEventAttributes(
            marker_name=SIDE_EFFECT_MARKER_NAME,
            details=Payload(data=encode_marker_details("0", b"recorded")),
        )
    )

    assert machine.get_decision() is None


async def test_marker_state_machine_not_cancellable():
    attrs = decision.RecordMarkerDecisionAttributes(marker_name=SIDE_EFFECT_MARKER_NAME)
    machine = MarkerStateMachine(attrs, SIDE_EFFECT_MARKER_NAME, "0")

    assert machine.request_cancel() is False
    assert machine.get_decision() == decision.Decision(
        record_marker_decision_attributes=attrs
    )


async def test_marker_state_machine_preserves_details_and_header():
    encoded = encode_marker_details("0", b"payload")
    attrs = decision.RecordMarkerDecisionAttributes(
        marker_name=SIDE_EFFECT_MARKER_NAME,
        details=Payload(data=encoded),
        header=Header(fields={"key": Payload(data=b"value")}),
    )
    machine = MarkerStateMachine(attrs, SIDE_EFFECT_MARKER_NAME, "0")

    emitted = machine.get_decision()

    assert emitted == decision.Decision(record_marker_decision_attributes=attrs)
    assert emitted.record_marker_decision_attributes.details == Payload(data=encoded)
    assert emitted.record_marker_decision_attributes.header == Header(
        fields={"key": Payload(data=b"value")}
    )


async def test_marker_state_machine_id_uses_type_context_format():
    attrs = decision.RecordMarkerDecisionAttributes(marker_name=SIDE_EFFECT_MARKER_NAME)
    machine = MarkerStateMachine(attrs, SIDE_EFFECT_MARKER_NAME, "42")

    assert machine.get_id().id == "SideEffect_42"


async def test_encode_decode_marker_details_roundtrip():
    context_id = "my-id"
    user_data = b"hello world"

    encoded = encode_marker_details(context_id, user_data)
    decoded_id, decoded_data = decode_marker_details(encoded)

    assert decoded_id == context_id
    assert decoded_data == user_data


async def test_decode_marker_details_no_encoding_returns_none():
    # Raw payload with no length-prefix encoding — treated as from another SDK.
    decoded_id, decoded_data = decode_marker_details(b"raw-history-value")

    assert decoded_id is None
    assert decoded_data == b"raw-history-value"


async def test_encode_decode_marker_details_empty_user_data():
    encoded = encode_marker_details("0", b"")
    context_id, user_data = decode_marker_details(encoded)

    assert context_id == "0"
    assert user_data == b""
