import dataclasses
from typing import Any, Type, Optional

import pytest

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DefaultDataConverter
from msgspec import json


@dataclasses.dataclass
class _TestDataClass:
    foo: str = "foo"
    bar: int = -1
    baz: Optional["_TestDataClass"] = None


@pytest.mark.parametrize(
    "json,types,expected",
    [
        pytest.param('"Hello world"', [str], ["Hello world"], id="happy path"),
        pytest.param(
            '"Hello" "world"', [str, str], ["Hello", "world"], id="space delimited"
        ),
        pytest.param("1", [int, int], [1, 0], id="ints"),
        pytest.param("1.5", [float, float], [1.5, 0.0], id="floats"),
        pytest.param("true", [bool, bool], [True, False], id="bools"),
        pytest.param(
            '{"foo": "hello world", "bar": 42, "baz": {"bar": 43}}',
            [_TestDataClass, _TestDataClass],
            [_TestDataClass("hello world", 42, _TestDataClass(bar=43)), None],
            id="data classes",
        ),
        pytest.param(
            '{"foo": "hello world"}',
            [dict, dict],
            [{"foo": "hello world"}, None],
            id="dicts",
        ),
        pytest.param(
            '{"foo": 52}',
            [dict[str, int], dict],
            [{"foo": 52}, None],
            id="generic dicts",
        ),
        pytest.param(
            '["hello"]', [list[str], list[str]], [["hello"], None], id="lists"
        ),
        pytest.param('["hello"]', [set[str], set[str]], [{"hello"}, None], id="sets"),
        pytest.param(
            '["hello", "world"]', [list[str]], [["hello", "world"]], id="list"
        ),
        pytest.param(
            '{"foo": "bar"} {"bar": 100} ["hello"] "world"',
            [_TestDataClass, _TestDataClass, list[str], str],
            [_TestDataClass(foo="bar"), _TestDataClass(bar=100), ["hello"], "world"],
            id="space delimited mix",
        ),
        pytest.param("", [], [], id="no input expected"),
        pytest.param("", [str], [None], id="no input unexpected"),
        pytest.param(
            '"hello world" {"foo":"bar"} 7',
            [None, None, None],
            ["hello world", {"foo": "bar"}, 7],
            id="no type hints",
        ),
        pytest.param(
            '"hello" "world" "goodbye"',
            [str, str],
            ["hello", "world"],
            id="extra content",
        ),
    ],
)
def test_data_converter_from_data(
    json: str, types: list[Type], expected: list[Any]
) -> None:
    converter = DefaultDataConverter()
    actual = converter.from_data(Payload(data=json.encode()), types)
    assert expected == actual


@pytest.mark.parametrize(
    "values,expected",
    [
        pytest.param(["hello world"], '"hello world"', id="happy path"),
        pytest.param(["hello", "world"], '"hello" "world"', id="multiple values"),
        pytest.param([[["hello"]], ["world"]], '[["hello"]] ["world"]', id="lists"),
        pytest.param([1, 2, 10], "1 2 10", id="numeric values"),
        pytest.param([True, False], "true false", id="bool values"),
        pytest.param(
            [{"foo": "foo", "bar": 20}], '{"bar":20,"foo":"foo"}', id="dict values"
        ),
        pytest.param([{"foo", "bar"}], '["bar","foo"]', id="set values"),
        pytest.param(
            [_TestDataClass()], '{"foo":"foo","bar":-1,"baz":null}', id="data classes"
        ),
    ],
)
def test_data_converter_to_data(values: list[Any], expected: str) -> None:
    converter = DefaultDataConverter()
    converter._encoder = json.Encoder(order="deterministic")
    actual = converter.to_data(values)
    assert actual.data.decode() == expected
