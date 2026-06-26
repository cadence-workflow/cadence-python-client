from typing import cast

from cadence._internal.workflow.statemachine.decision_state_machine import (
    BaseDecisionStateMachine,
    DecisionId,
    DecisionState,
    DecisionType,
)
from cadence._internal.workflow.statemachine.event_dispatcher import EventDispatcher
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload

MARKER_ID_HEADER_KEY = "__cadence_python_marker_id"

marker_events = EventDispatcher()


def attach_marker_id(
    attrs: decision.RecordMarkerDecisionAttributes,
    marker_id: str,
) -> decision.RecordMarkerDecisionAttributes:
    attrs.header.fields[MARKER_ID_HEADER_KEY].CopyFrom(
        Payload(data=marker_id.encode("utf-8"))
    )
    return attrs


def marker_id_from_attrs(
    attrs: decision.RecordMarkerDecisionAttributes
    | history.MarkerRecordedEventAttributes,
) -> str | None:
    if MARKER_ID_HEADER_KEY not in attrs.header.fields:
        return None
    return cast(str, attrs.header.fields[MARKER_ID_HEADER_KEY].data.decode("utf-8"))


class MarkerStateMachine(BaseDecisionStateMachine):
    """State machine for RecordMarker decisions."""

    request: decision.RecordMarkerDecisionAttributes
    _marker_id: str

    def __init__(
        self,
        request: decision.RecordMarkerDecisionAttributes,
        marker_id: str,
    ) -> None:
        super().__init__()
        self.request = request
        self._marker_id = marker_id

    def get_id(self) -> DecisionId:
        return DecisionId(DecisionType.MARKER, self._marker_id)

    def get_decision(self) -> decision.Decision | None:
        if self.state is DecisionState.REQUESTED:
            return decision.Decision(record_marker_decision_attributes=self.request)
        return None

    def request_cancel(self) -> bool:
        return False

    @marker_events.event()
    def handle_recorded(self, _: history.MarkerRecordedEventAttributes) -> None:
        self._transition(DecisionState.COMPLETED)
