from dataclasses import dataclass

import pytest

from cadence._internal.workflow.memo import memo_to_proto
from cadence.data_converter import DefaultDataConverter


def test_memo_to_proto_none() -> None:
    dc = DefaultDataConverter()
    assert memo_to_proto(dc, None) is None


def test_memo_to_proto_empty_dict() -> None:
    dc = DefaultDataConverter()
    assert memo_to_proto(dc, {}) is None


def test_memo_to_proto_single_key_matches_to_data() -> None:
    dc = DefaultDataConverter()
    proto = memo_to_proto(dc, {"k": "v"})
    assert proto is not None
    assert list(proto.fields.keys()) == ["k"]
    assert proto.fields["k"] == dc.to_data(["v"])


def test_memo_to_proto_multiple_keys() -> None:
    dc = DefaultDataConverter()
    proto = memo_to_proto(dc, {"a": 1, "b": "two", "c": {"x": 3}})
    assert proto is not None
    assert proto.fields["a"] == dc.to_data([1])
    assert proto.fields["b"] == dc.to_data(["two"])
    assert proto.fields["c"] == dc.to_data([{"x": 3}])


@dataclass
class _Sample:
    x: int
    y: str


def test_memo_to_proto_dataclass_value() -> None:
    dc = DefaultDataConverter()
    obj = _Sample(7, "z")
    proto = memo_to_proto(dc, {"obj": obj})
    assert proto is not None
    assert proto.fields["obj"] == dc.to_data([obj])


def test_memo_to_proto_encoding_error_propagates() -> None:
    dc = DefaultDataConverter()
    with pytest.raises(Exception):
        memo_to_proto(dc, {"bad": object()})
