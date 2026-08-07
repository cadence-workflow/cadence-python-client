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


class MarkerHeader(Struct, omit_defaults=True):
    context_id: str
    mutable_side_effect_id: str | None = None
    mutable_side_effect_access_count: int | None = None


def encode_marker_header(
    context_id: str,
    *,
    mutable_side_effect_id: str | None = None,
    mutable_side_effect_access_count: int | None = None,
) -> Payload:
    """Serialize marker metadata for storage under MARKER_HEADER_KEY."""
    return Payload(
        data=json.encode(
            MarkerHeader(
                context_id=context_id,
                mutable_side_effect_id=mutable_side_effect_id,
                mutable_side_effect_access_count=mutable_side_effect_access_count,
            )
        )
    )


def marker_header(
    attrs: decision.RecordMarkerDecisionAttributes
    | history.MarkerRecordedEventAttributes,
) -> MarkerHeader | None:
    """Decode the marker header, returning None for foreign markers."""
    if MARKER_HEADER_KEY not in attrs.header.fields:
        return None
    try:
        return json.decode(
            attrs.header.fields[MARKER_HEADER_KEY].data, type=MarkerHeader
        )
    except DecodeError:
        return None


def has_marker_header(
    attrs: decision.RecordMarkerDecisionAttributes
    | history.MarkerRecordedEventAttributes,
) -> bool:
    """Return whether this marker attempts to use the Python MarkerHeader format."""
    return MARKER_HEADER_KEY in attrs.header.fields


def marker_context_id(
    attrs: decision.RecordMarkerDecisionAttributes
    | history.MarkerRecordedEventAttributes,
) -> str | None:
    """Read the context_id from a marker's Header.

    record_marker always sets the header and callers filter the immediate-cancellation
    marker upstream, so None is a defensive fallback for a missing/malformed header, not
    a case hit in normal replay.
    """
    header = marker_header(attrs)
    return header.context_id if header is not None else None


def mutable_side_effect_marker_info(
    attrs: decision.RecordMarkerDecisionAttributes
    | history.MarkerRecordedEventAttributes,
) -> tuple[str, int] | None:
    """Return a mutable side effect marker's stable ID and invocation count."""
    if attrs.marker_name != MUTABLE_SIDE_EFFECT_MARKER_NAME:
        return None
    header = marker_header(attrs)
    if (
        header is None
        or header.mutable_side_effect_id is None
        or header.mutable_side_effect_access_count is None
    ):
        return None
    return (
        header.mutable_side_effect_id,
        header.mutable_side_effect_access_count,
    )


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
    _recorded: bool

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
        self._recorded = False

    @classmethod
    def completed(
        cls,
        request: decision.RecordMarkerDecisionAttributes,
        marker_name: str,
        context_id: str,
    ) -> "MarkerStateMachine":
        machine = cls(request, marker_name, context_id)
        machine._transition(DecisionState.COMPLETED)
        return machine

    def get_id(self) -> DecisionId:
        return marker_decision_id(self._marker_name, self._context_id)

    def get_result(self) -> Payload:
        return Payload(data=self.request.details.data)

    @property
    def was_recorded(self) -> bool:
        return self._recorded

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(record_marker_decision_attributes=self.request)
        return None

    def request_cancel(self, message: str | None = None) -> bool:
        return False

    @marker_events.event()
    def handle_recorded(self, attrs: history.MarkerRecordedEventAttributes) -> None:
        self.request.details.CopyFrom(attrs.details)
        self._recorded = True
        self._transition(DecisionState.COMPLETED)
