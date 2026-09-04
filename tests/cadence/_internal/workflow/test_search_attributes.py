from datetime import datetime, timezone

import pytest

from cadence._internal.workflow.search_attributes import (
    decode_indexed_field,
    search_attributes_from_proto,
    search_attributes_to_proto,
)
from cadence.api.v1.common_pb2 import Payload
from cadence.workflow import SearchAttributeType


def test_search_attributes_to_proto_none() -> None:
    assert search_attributes_to_proto(None) is None


def test_search_attributes_to_proto_empty_dict() -> None:
    assert search_attributes_to_proto({}) is None


def test_search_attributes_to_proto_json_encodes_each_value() -> None:
    proto = search_attributes_to_proto({"k": "v"})
    assert proto is not None
    assert list(proto.indexed_fields.keys()) == ["k"]
    assert proto.indexed_fields["k"].data == b'"v"'


def test_search_attributes_to_proto_scalar_types() -> None:
    proto = search_attributes_to_proto({"a": 1, "b": "two", "c": True, "d": 1.5})
    assert proto is not None
    assert proto.indexed_fields["a"].data == b"1"
    assert proto.indexed_fields["b"].data == b'"two"'
    assert proto.indexed_fields["c"].data == b"true"
    assert proto.indexed_fields["d"].data == b"1.5"


def test_search_attributes_to_proto_list_values() -> None:
    proto = search_attributes_to_proto({"keywords": ["a", "b"]})
    assert proto is not None
    assert proto.indexed_fields["keywords"].data == b'["a","b"]'


def test_search_attributes_to_proto_list_of_ints() -> None:
    proto = search_attributes_to_proto({"CustomIntField": [1, 2, 3]})
    assert proto is not None
    assert proto.indexed_fields["CustomIntField"].data == b"[1,2,3]"
    assert search_attributes_from_proto(proto) == {"CustomIntField": [1, 2, 3]}


def test_search_attributes_to_proto_datetime_rfc3339() -> None:
    proto = search_attributes_to_proto(
        {"CustomDatetimeField": datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)}
    )
    assert proto is not None
    assert proto.indexed_fields["CustomDatetimeField"].data == (
        b'"2024-01-15T10:30:00Z"'
    )


def test_search_attributes_round_trip() -> None:
    original: dict[str, SearchAttributeType | list[SearchAttributeType]] = {
        "CustomIntField": 2,
        "CustomKeywordField": "seattle",
    }
    proto = search_attributes_to_proto(original)
    assert proto is not None
    assert search_attributes_from_proto(proto) == original


def test_search_attributes_to_proto_encoding_error_propagates() -> None:
    with pytest.raises(TypeError):
        search_attributes_to_proto({"bad": object()})  # type: ignore[dict-item]


def test_decode_indexed_field_ignores_json_whitespace() -> None:
    compact = Payload(data=b'{"a":1,"b":[2,3]}')
    padded = Payload(data=b' { "b" : [ 2 , 3 ] , "a" : 1 } ')
    assert decode_indexed_field(compact) == decode_indexed_field(padded)


def test_decode_indexed_field_detects_value_mismatch() -> None:
    assert decode_indexed_field(Payload(data=b"1")) != decode_indexed_field(
        Payload(data=b"2")
    )


def test_decode_indexed_field_non_json_falls_back_to_bytes() -> None:
    raw = Payload(data=b"\xff not json")
    assert decode_indexed_field(raw) == b"\xff not json"
