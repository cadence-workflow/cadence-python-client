from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionId,
    DecisionType,
)
from cadence._internal.workflow.statemachine.marker_state_machine import (
    MarkerStateMachine,
    encode_marker_header,
    marker_context_id,
    marker_decision_id,
    MARKER_HEADER_KEY,
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
            details=Payload(data=b"recorded"),
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
    attrs = decision.RecordMarkerDecisionAttributes(
        marker_name=SIDE_EFFECT_MARKER_NAME,
        details=Payload(data=b"payload"),
        header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("0")}),
    )
    machine = MarkerStateMachine(attrs, SIDE_EFFECT_MARKER_NAME, "0")

    emitted = machine.get_decision()

    assert emitted == decision.Decision(record_marker_decision_attributes=attrs)
    # Details stay the raw user payload; the context_id lives in the header.
    assert emitted.record_marker_decision_attributes.details == Payload(data=b"payload")
    assert marker_context_id(emitted.record_marker_decision_attributes) == "0"


async def test_marker_state_machine_id_uses_type_context_format():
    attrs = decision.RecordMarkerDecisionAttributes(marker_name=SIDE_EFFECT_MARKER_NAME)
    machine = MarkerStateMachine(attrs, SIDE_EFFECT_MARKER_NAME, "42")

    assert machine.get_id() == marker_decision_id(SIDE_EFFECT_MARKER_NAME, "42")
    assert machine.get_id().id == "SideEffect_42"


async def test_marker_decision_id_format():
    # This format is the single source of truth for marker DecisionIds — every lookup
    # (routing, the replay details cache, non-determinism expectations) must derive its
    # key from marker_decision_id rather than reconstructing the string inline.
    assert marker_decision_id(SIDE_EFFECT_MARKER_NAME, "0") == DecisionId(
        DecisionType.MARKER, "SideEffect_0"
    )


async def test_marker_context_id_roundtrip():
    attrs = history.MarkerRecordedEventAttributes(
        marker_name=SIDE_EFFECT_MARKER_NAME,
        details=Payload(data=b"hello world"),
        header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("my-id")}),
    )

    assert marker_context_id(attrs) == "my-id"
    # The payload is untouched by the metadata encoding.
    assert attrs.details == Payload(data=b"hello world")


async def test_marker_context_id_absent_header_returns_none():
    # A marker with no marker header — e.g. from another SDK or pre-header history.
    attrs = history.MarkerRecordedEventAttributes(
        marker_name=SIDE_EFFECT_MARKER_NAME,
        details=Payload(data=b"raw-history-value"),
    )

    assert marker_context_id(attrs) is None


async def test_marker_context_id_ignores_unrelated_header_keys():
    # A header that carries other keys but not ours is treated as having no context_id.
    attrs = history.MarkerRecordedEventAttributes(
        marker_name=SIDE_EFFECT_MARKER_NAME,
        header=Header(fields={"SomethingElse": Payload(data=b"value")}),
    )

    assert marker_context_id(attrs) is None


async def test_marker_context_id_malformed_header_returns_none():
    # Garbage under our header key must be treated as absent rather than raising.
    attrs = history.MarkerRecordedEventAttributes(
        marker_name=SIDE_EFFECT_MARKER_NAME,
        header=Header(fields={MARKER_HEADER_KEY: Payload(data=b"not-json")}),
    )

    assert marker_context_id(attrs) is None
