"""Convert user memo maps to/from protobuf :class:`cadence.api.v1.common_pb2.Memo`."""

from __future__ import annotations

from typing import Any, Mapping

from cadence.api.v1 import common_pb2
from cadence.data_converter import DataConverter


def memo_to_proto(
    data_converter: DataConverter,
    memo: Mapping[str, Any] | None,
) -> common_pb2.Memo | None:
    """Serialize ``memo`` to protobuf, or ``None`` if no memo was provided.

    Each value is encoded as a single-element list via the data converter,
    matching Go/Java SDK behavior (one :class:`Payload` per key).
    """
    if not memo:
        return None
    out = common_pb2.Memo()
    for key, value in memo.items():
        out.fields[key].CopyFrom(data_converter.to_data([value]))
    return out


def memo_from_proto(
    data_converter: DataConverter,
    memo: common_pb2.Memo,
) -> dict[str, Any]:
    """Deserialize a protobuf ``Memo`` back to a plain dict.

    Each field payload was encoded as a single-element list; we unwrap that
    first element to recover the original value.
    """
    return {
        key: data_converter.from_data(payload, [None])[0]
        for key, payload in memo.fields.items()
    }
