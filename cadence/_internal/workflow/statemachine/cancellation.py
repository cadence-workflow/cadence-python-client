from typing import Dict, Any, Tuple

from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionId,
    DecisionType,
)

from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload
from msgspec import json


MARKER_PREFIX = "Cancel_"


def is_immediate_cancel(marker: history.MarkerRecordedEventAttributes) -> bool:
    return marker.marker_name.startswith(MARKER_PREFIX)


def to_marker(
    decision_id: DecisionId, props: Dict[str, Any]
) -> decision.RecordMarkerDecisionAttributes:
    data = props | {"type": decision_id.decision_type.name}
    return decision.RecordMarkerDecisionAttributes(
        marker_name=MARKER_PREFIX + decision_id.id,
        details=Payload(data=json.encode(data)),
    )


def from_marker(
    marker: history.MarkerRecordedEventAttributes,
) -> Tuple[DecisionId, Dict[str, Any]]:
    decision_id = marker.marker_name.replace(MARKER_PREFIX, "")
    props = json.decode(marker.details.data)
    decision_type = DecisionType[props.pop("type")]
    return DecisionId(decision_type, decision_id), props
