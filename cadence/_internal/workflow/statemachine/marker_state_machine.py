from msgspec import DecodeError, Struct, json

from cadence._internal.workflow.statemachine.decision_state_machine import (
    BaseDecisionStateMachine,
    DecisionId,
    DecisionState,
    DecisionType,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload

# Marker type names match the Go SDK constants:
# https://github.com/cadence-workflow/cadence-go-client/blob/727b555be0fd0f65ad201832ba078b661919034e/internal/internal_decision_state_machine.go#L160-L163
SIDE_EFFECT_MARKER_NAME = "SideEffect"
VERSION_MARKER_NAME = "Version"
LOCAL_ACTIVITY_MARKER_NAME = "LocalActivity"
MUTABLE_SIDE_EFFECT_MARKER_NAME = "MutableSideEffect"

# TODO(local-activities): when we implement LocalActivity markers, keep the split of
# metadata in the Header and the raw payload in the Details. Storing the DecisionID under a
# consistent header key too may simplify the code, though each marker type will always need
# some custom logic. LocalActivity is the hard case: it must also carry a Failure
# (reason: str, details: bytes), so MarkerHeader will need to grow to represent that.

KNOWN_MARKER_NAMES = frozenset(
    {
        SIDE_EFFECT_MARKER_NAME,
        VERSION_MARKER_NAME,
        LOCAL_ACTIVITY_MARKER_NAME,
        MUTABLE_SIDE_EFFECT_MARKER_NAME,
    }
)

MARKER_HEADER_KEY = "MarkerHeader"

marker_events = EventDispatcher()


class MarkerHeader(Struct):
    context_id: str


def encode_marker_header(context_id: str) -> Payload:
    """Serialize marker metadata for storage under MARKER_HEADER_KEY."""
    return Payload(data=json.encode(MarkerHeader(context_id=context_id)))


def marker_context_id(
    attrs: decision.RecordMarkerDecisionAttributes
    | history.MarkerRecordedEventAttributes,
) -> str | None:
    """Read the context_id from a marker's Header.

    record_marker always sets the header and callers filter the immediate-cancellation
    marker upstream, so None is a defensive fallback for a missing/malformed header, not
    a case hit in normal replay.
    """
    if MARKER_HEADER_KEY not in attrs.header.fields:
        return None
    try:
        return json.decode(
            attrs.header.fields[MARKER_HEADER_KEY].data, type=MarkerHeader
        ).context_id
    except DecodeError:
        return None


def marker_decision_id(marker_name: str, context_id: str) -> DecisionId:
    """Build the DecisionId that identifies a marker instance.

    Format matches the Go SDK's fmt.Sprintf("%v_%v", markerName, contextID):
    https://github.com/cadence-workflow/cadence-go-client/blob/727b555be0fd0f65ad201832ba078b661919034e/internal/internal_decision_state_machine.go#L794
    """
    return DecisionId(DecisionType.MARKER, f"{marker_name}_{context_id}")


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
        return marker_decision_id(self._marker_name, self._context_id)

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(record_marker_decision_attributes=self.request)
        return None

    def request_cancel(self, message: str | None = None) -> bool:
        return False

    @marker_events.event()
    def handle_recorded(self, _: history.MarkerRecordedEventAttributes) -> None:
        self._transition(DecisionState.COMPLETED)
