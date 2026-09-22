import dataclasses
from typing import Any, Optional, Type, TypedDict, Union, cast

import pytest
from msgspec import json

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DefaultDataConverter


@dataclasses.dataclass
class _TestDataClass:
    foo: str = "foo"
    bar: int = -1
    baz: Optional["_TestDataClass"] = None


@dataclasses.dataclass
class _RequiredDataClass:
    foo: str
    bar: int


class _ItemDict(TypedDict):
    name: str
    count: int


class _BaseItem(TypedDict):
    id: str


class _DetailedItem(TypedDict):
    id: str
    name: str


class _OptionalItem(TypedDict, total=False):
    note: str


class _NestedItem(TypedDict):
    item: _RequiredDataClass | _ItemDict


@dataclasses.dataclass(frozen=True)
class _NamedItem:
    name: str
    count: int


@dataclasses.dataclass(frozen=True)
class _FooItem:
    foo: str
    bar: int


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
        pytest.param("", [Any], [None], id="no input unexpected any"),
        pytest.param(
            '"hello world" {"foo":"bar"} 7',
            [None, None, None],
            ["hello world", {"foo": "bar"}, 7],
            id="no type hints",
        ),
        pytest.param(
            '"hello"',
            [str, Any, None],
            ["hello", None, None],
            id="short input with untyped hints",
        ),
        pytest.param(
            '"hello" "world" "goodbye"',
            [str, str],
            ["hello", "world"],
            id="extra content",
        ),
        pytest.param(
            '{"foo": "hello", "bar": 42}',
            [_RequiredDataClass | _ItemDict],
            [_RequiredDataClass(foo="hello", bar=42)],
            id="union dataclass first",
        ),
        pytest.param(
            '{"name": "widget", "count": 3}',
            [_RequiredDataClass | _ItemDict],
            [{"name": "widget", "count": 3}],
            id="union typed dict fallback",
        ),
        pytest.param(
            '{"name": "widget", "count": 3}',
            [Union[_ItemDict, _RequiredDataClass]],
            [{"name": "widget", "count": 3}],
            id="union typed dict first",
        ),
        pytest.param(
            "null",
            [cast(Type, _RequiredDataClass | _ItemDict | None)],
            [None],
            id="union optional none",
        ),
        pytest.param(
            '[{"foo": "hello", "bar": 42}, {"name": "widget", "count": 3}]',
            [cast(Type, list[_RequiredDataClass | _ItemDict])],
            [
                [
                    _RequiredDataClass(foo="hello", bar=42),
                    {"name": "widget", "count": 3},
                ]
            ],
            id="union nested in list",
        ),
        pytest.param(
            '{"id": "1", "name": "detailed"}',
            [cast(Type, _BaseItem | _DetailedItem)],
            [{"id": "1", "name": "detailed"}],
            id="union prefers variant covering all keys",
        ),
        pytest.param(
            '{"name": "widget", "count": 3}',
            [cast(Type, _OptionalItem | _ItemDict)],
            [{"name": "widget", "count": 3}],
            id="union does not select unrelated all-optional variant",
        ),
        pytest.param(
            '{"name": "widget", "count": 3}',
            [cast(Type, _TestDataClass | _ItemDict)],
            [{"name": "widget", "count": 3}],
            id="union does not select unrelated defaulted dataclass",
        ),
        pytest.param(
            '{"first": {"foo": "hello", "bar": 42}, '
            '"second": {"name": "widget", "count": 3}}',
            [cast(Type, dict[str, _RequiredDataClass | _ItemDict])],
            [
                {
                    "first": _RequiredDataClass(foo="hello", bar=42),
                    "second": {"name": "widget", "count": 3},
                }
            ],
            id="union nested in dict values",
        ),
        pytest.param(
            '[{"foo": "hello", "bar": 42}, {"name": "widget", "count": 3}]',
            [
                cast(
                    Type,
                    tuple[_RequiredDataClass | _ItemDict, ...],
                )
            ],
            [
                (
                    _RequiredDataClass(foo="hello", bar=42),
                    {"name": "widget", "count": 3},
                )
            ],
            id="union nested in tuple",
        ),
        pytest.param(
            '[{"foo": "hello", "bar": 42}, {"name": "widget", "count": 3}]',
            [cast(Type, set[_FooItem | _NamedItem])],
            [
                {
                    _FooItem(foo="hello", bar=42),
                    _NamedItem(name="widget", count=3),
                }
            ],
            id="union nested in set",
        ),
        pytest.param(
            '{"item": {"name": "widget", "count": 3}}',
            [_NestedItem],
            [{"item": {"name": "widget", "count": 3}}],
            id="union nested in typed dict field",
        ),
    ],
)
def test_data_converter_from_data(
    json: str, types: list[Type | None], expected: list[Any]
) -> None:
    converter = DefaultDataConverter()
    actual = converter.from_data(Payload(data=json.encode()), types)
    assert expected == actual


def test_from_data_union_no_matching_variant_raises() -> None:
    converter = DefaultDataConverter()
    with pytest.raises(
        TypeError, match="Unable to convert value into any union variant"
    ):
        converter.from_data(
            Payload(data=b'{"other": true}'),
            [cast(Type, _RequiredDataClass | _ItemDict)],
        )


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
