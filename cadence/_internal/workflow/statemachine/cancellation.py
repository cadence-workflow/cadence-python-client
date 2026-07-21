from typing import Dict, Any, Tuple

from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionId,
    DecisionType,
)

from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload
from msgspec import json


CANCEL_MARKER_NAME = "Cancel"


def is_immediate_cancel(marker: history.MarkerRecordedEventAttributes) -> bool:
    return marker.marker_name == CANCEL_MARKER_NAME


def to_marker(
    decision_id: DecisionId, props: Dict[str, Any]
) -> decision.RecordMarkerDecisionAttributes:
    data = props | {"id": decision_id.id, "type": decision_id.decision_type.name}
    return decision.RecordMarkerDecisionAttributes(
        marker_name=CANCEL_MARKER_NAME,
        details=Payload(data=json.encode(data)),
    )


def from_marker(
    marker: history.MarkerRecordedEventAttributes,
) -> Tuple[DecisionId, Dict[str, Any]]:
    props = json.decode(marker.details.data)
    decision_id = DecisionId(DecisionType[props.pop("type")], props.pop("id"))
    return decision_id, props
