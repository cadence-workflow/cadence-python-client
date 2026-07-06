from msgspec import DecodeError, json

from cadence._internal.workflow.statemachine.decision_state_machine import (
    BaseDecisionStateMachine,
    DecisionId,
    DecisionState,
    DecisionType,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence.api.v1 import decision, history

# Marker type names match the Go SDK constants:
# https://github.com/cadence-workflow/cadence-go-client/blob/727b555be0fd0f65ad201832ba078b661919034e/internal/internal_decision_state_machine.go#L160-L163
SIDE_EFFECT_MARKER_NAME = "SideEffect"
VERSION_MARKER_NAME = "Version"
LOCAL_ACTIVITY_MARKER_NAME = "LocalActivity"
MUTABLE_SIDE_EFFECT_MARKER_NAME = "MutableSideEffect"

KNOWN_MARKER_NAMES = frozenset(
    {
        SIDE_EFFECT_MARKER_NAME,
        VERSION_MARKER_NAME,
        LOCAL_ACTIVITY_MARKER_NAME,
        MUTABLE_SIDE_EFFECT_MARKER_NAME,
    }
)

marker_events = EventDispatcher()


def encode_marker_details(context_id: str, user_data: bytes) -> bytes:
    """Encode [context_id, user_data] into a single bytes value stored in Details.

    JSON array, mirroring how the Go SDK's encodeArgs(dataConverter, [id, result])
    stores the pair for SideEffect/Version/MutableSideEffect markers.
    """
    return json.encode((context_id, user_data))


def decode_marker_details(data: bytes) -> tuple[str | None, bytes]:
    """Decode Details bytes back to (context_id, user_data).

    Returns (None, data) if the encoding is absent or malformed (e.g. markers from
    other SDKs or pre-encoding history).
    """
    try:
        context_id, user_data = json.decode(data, type=tuple[str, bytes])
    except DecodeError:
        return None, data
    return context_id, user_data


class MarkerStateMachine(BaseDecisionStateMachine):
    """State machine for RecordMarker decisions."""

    request: decision.RecordMarkerDecisionAttributes
    _marker_name: str
    _context_id: str

    def __init__(
        self,
        request: decision.RecordMarkerDecisionAttributes,
        marker_name: str,
        context_id: str,
    ) -> None:
        super().__init__()
        self.request = request
        self._marker_name = marker_name
        self._context_id = context_id

    def get_id(self) -> DecisionId:
        # ID format matches the Go SDK's fmt.Sprintf("%v_%v", markerName, contextID):
        # https://github.com/cadence-workflow/cadence-go-client/blob/727b555be0fd0f65ad201832ba078b661919034e/internal/internal_decision_state_machine.go#L794
        return DecisionId(
            DecisionType.MARKER, f"{self._marker_name}_{self._context_id}"
        )

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(record_marker_decision_attributes=self.request)
        return None

    def request_cancel(self) -> bool:
        return False

    @marker_events.event()
    def handle_recorded(self, _: history.MarkerRecordedEventAttributes) -> None:
        self._transition(DecisionState.COMPLETED)
