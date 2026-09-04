"""Convert user search-attribute maps to/from protobuf SearchAttributes.

Cadence indexes these values with ``encoding/json`` on the server
(``DeserializeSearchAttributeValue``). Encoding must match Go's
``json.Marshal`` of each value, not the workflow :class:`DataConverter`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from cadence.api.v1 import common_pb2
from cadence.workflow import SearchAttributeType


def search_attributes_to_proto(
    attributes: Mapping[str, SearchAttributeType | list[SearchAttributeType]] | None,
) -> common_pb2.SearchAttributes | None:
    """Serialize ``attributes`` to protobuf, or ``None`` if none were provided."""
    if not attributes:
        return None
    out = common_pb2.SearchAttributes()
    for key, value in attributes.items():
        out.indexed_fields[key].CopyFrom(
            common_pb2.Payload(data=_encode_indexed_value(value))
        )
    return out


def search_attributes_from_proto(
    attributes: common_pb2.SearchAttributes,
) -> dict[str, Any]:
    """Deserialize protobuf search attributes back to a plain dict."""
    return {
        key: decode_indexed_field(payload)
        for key, payload in attributes.indexed_fields.items()
    }


def decode_indexed_field(payload: common_pb2.Payload) -> Any:
    """Decode an indexed-field payload the way Cadence server does.

    Server decoding is ``json.Unmarshal`` into the registered value type
    (string, int64, float64, bool, time.Time, or a list of the same). Without
    the type map we unmarshal into a generic JSON value. Non-JSON payloads
    fall back to the original bytes.
    """
    try:
        return json.loads(payload.data.decode())
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return payload.data


def _encode_indexed_value(
    value: SearchAttributeType | list[SearchAttributeType],
) -> bytes:
    return json.dumps(
        value,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.isoformat().replace("+00:00", "Z")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
