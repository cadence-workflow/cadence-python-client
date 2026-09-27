import dataclasses
import enum
import uuid
from datetime import date, datetime, timezone
from typing import (
    Annotated,
    Any,
    NotRequired,
    Optional,
    Required,
    Type,
    TypedDict,
    Union,
)

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from cadence._internal.fn_signature import FnSignature
from cadence.api.v1.common_pb2 import Payload
from cadence.contrib.pydantic import PydanticDataConverter
from cadence.data_converter import DefaultDataConverter


@dataclasses.dataclass
class _TestDataClass:
    foo: str = "foo"
    bar: int = -1
    baz: Optional["_TestDataClass"] = None


class _Status(enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class _TestModel(BaseModel):
    foo: str = "foo"
    bar: int = -1
    nested: Optional["_TestModel"] = None


class _TimedModel(BaseModel):
    when: datetime
    day: date


class _UuidModel(BaseModel):
    id: uuid.UUID


class _ItemDict(TypedDict):
    name: str
    count: int


@dataclasses.dataclass
class _RequiredDataClass:
    foo: str
    bar: int


@dataclasses.dataclass(frozen=True)
class _FooItem:
    foo: str


@dataclasses.dataclass(frozen=True)
class _NamedItem:
    name: str


class _BaseItem(TypedDict):
    id: str


class _DetailedItem(TypedDict):
    id: str
    name: str


class _OptionalItem(TypedDict, total=False):
    note: str


class _NestedItem(TypedDict):
    item: Union[_RequiredDataClass, _ItemDict]


class _BaseOptionalItem(TypedDict):
    name: str


class _InheritedOptionalItem(_BaseOptionalItem, total=False):
    note: str


class _NullableItem(TypedDict):
    name: str
    note: NotRequired[Optional[str]]


class _AnyNullItem(TypedDict):
    name: str
    extra: NotRequired[Any]


class _MixedTotalItem(TypedDict, total=False):
    name: Required[str]
    note: str


@dataclasses.dataclass
class _WrapperDataClass:
    items: list[Union[_RequiredDataClass, _ItemDict]]
    note: Optional[str] = None


class _RejectingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required_field: str


class _DictWithHookedField(TypedDict):
    name: str
    model: _RejectingModel


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
            '{"foo": "hello world", "bar": 42, "nested": {"bar": 43}}',
            [_TestModel, _TestModel],
            [_TestModel(foo="hello world", bar=42, nested=_TestModel(bar=43)), None],
            id="pydantic models",
        ),
        pytest.param(
            '{"foo": "hello world", "bar": 42, "baz": {"bar": 43}}',
            [_TestDataClass, _TestDataClass],
            [_TestDataClass("hello world", 42, _TestDataClass(bar=43)), None],
            id="data classes",
        ),
        pytest.param(
            '{"name": "widget", "count": 3}',
            [_ItemDict],
            [{"name": "widget", "count": 3}],
            id="typed dict",
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
            [_TestModel, _TestDataClass, list[str], str],
            [_TestModel(foo="bar"), _TestDataClass(bar=100), ["hello"], "world"],
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
    ],
)
def test_from_data(json: str, types: list[Type | None], expected: list[Any]) -> None:
    converter = PydanticDataConverter()
    actual = converter.from_data(Payload(data=json.encode()), types)
    assert expected == actual


def test_from_data_empty_hints_decodes_single_value() -> None:
    converter = PydanticDataConverter()
    actual = converter.from_data(Payload(data=b'"hello"'), [])
    assert actual == ["hello"]


def test_from_data_invalid_payload_raises() -> None:
    converter = PydanticDataConverter()
    with pytest.raises(ValidationError):
        converter.from_data(Payload(data=b'"not-an-int"'), [int])


def test_default_converter_cannot_encode_pydantic_model() -> None:
    with pytest.raises(TypeError, match="unsupported"):
        DefaultDataConverter().to_data([_TestModel()])


def test_roundtrip_pydantic_model() -> None:
    converter = PydanticDataConverter()
    value = _TestModel(foo="hello", bar=7, nested=_TestModel(foo="inner", bar=8))
    payload = converter.to_data([value])
    assert converter.from_data(payload, [_TestModel]) == [value]


def test_roundtrip_datetime_fields() -> None:
    converter = PydanticDataConverter()
    value = _TimedModel(
        when=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
        day=date(2026, 3, 25),
    )
    payload = converter.to_data([value])
    assert converter.from_data(payload, [_TimedModel]) == [value]


def test_roundtrip_uuid() -> None:
    converter = PydanticDataConverter()
    value = _UuidModel(id=uuid.UUID("12345678-1234-5678-1234-567812345678"))
    payload = converter.to_data([value])
    assert converter.from_data(payload, [_UuidModel]) == [value]


def test_roundtrip_list_of_models() -> None:
    converter = PydanticDataConverter()
    values = [_TestModel(foo="a", bar=1), _TestModel(foo="b", bar=2)]
    payload = converter.to_data([values])
    assert converter.from_data(payload, [list[_TestModel]]) == [values]


def test_roundtrip_enum_value() -> None:
    converter = PydanticDataConverter()
    payload = converter.to_data([_Status.OPEN])
    assert payload.data.decode() == '"open"'
    assert converter.from_data(payload, [_Status]) == [_Status.OPEN]


@pytest.mark.parametrize(
    "values,expected",
    [
        pytest.param(["hello world"], '"hello world"', id="happy path"),
        pytest.param(["hello", "world"], '"hello" "world"', id="multiple values"),
        pytest.param([[["hello"]], ["world"]], '[["hello"]] ["world"]', id="lists"),
        pytest.param([1, 2, 10], "1 2 10", id="numeric values"),
        pytest.param([True, False], "true false", id="bool values"),
        pytest.param(
            [{"foo": "foo", "bar": 20}], '{"foo":"foo","bar":20}', id="dict values"
        ),
        pytest.param(
            [_TestModel()],
            '{"foo":"foo","bar":-1,"nested":null}',
            id="pydantic model",
        ),
        pytest.param(
            [_TestDataClass()], '{"foo":"foo","bar":-1,"baz":null}', id="data classes"
        ),
    ],
)
def test_to_data(values: list[Any], expected: str) -> None:
    converter = PydanticDataConverter()
    actual = converter.to_data(values)
    assert actual.data.decode() == expected


def test_to_data_unserializable_raises() -> None:
    converter = PydanticDataConverter()
    with pytest.raises(TypeError, match="unsupported"):
        converter.to_data([object()])


def _activity_with_defaults(model: _TestModel, flag: bool = True) -> None:
    pass


def test_params_from_payload_uses_python_defaults() -> None:
    signature = FnSignature.of(_activity_with_defaults)
    converter = PydanticDataConverter()
    payload = converter.to_data([_TestModel(foo="x", bar=3)])

    assert signature.params_from_payload(converter, payload) == [
        _TestModel(foo="x", bar=3),
        True,
    ]


@pytest.mark.parametrize(
    "json,types,expected",
    [
        pytest.param(
            '{"foo": "hello", "bar": 42}',
            [Union[_RequiredDataClass, _ItemDict]],
            [_RequiredDataClass("hello", 42)],
            id="union dataclass variant",
        ),
        pytest.param(
            '{"name": "widget", "count": 3}',
            [Union[_RequiredDataClass, _ItemDict]],
            [{"name": "widget", "count": 3}],
            id="union dict variant",
        ),
        pytest.param(
            '{"name": "widget", "count": 3}',
            [Union[_ItemDict, _RequiredDataClass]],
            [{"name": "widget", "count": 3}],
            id="union dict variant reversed order",
        ),
        pytest.param(
            "null",
            [Optional[Union[_RequiredDataClass, _ItemDict]]],
            [None],
            id="union optional none",
        ),
        pytest.param(
            '[{"foo": "a", "bar": 1}, {"name": "n", "count": 2}]',
            [list[Union[_RequiredDataClass, _ItemDict]]],
            [
                [_RequiredDataClass("a", 1), {"name": "n", "count": 2}],
            ],
            id="union nested in list",
        ),
        pytest.param(
            '{"first": {"foo": "a", "bar": 1}, "second": {"name": "n", "count": 2}}',
            [dict[str, Union[_RequiredDataClass, _ItemDict]]],
            [
                {
                    "first": _RequiredDataClass("a", 1),
                    "second": {"name": "n", "count": 2},
                }
            ],
            id="union nested in dict values",
        ),
        pytest.param(
            '[{"foo": "a", "bar": 1}, "note"]',
            [tuple[Union[_RequiredDataClass, _ItemDict], str]],
            [(_RequiredDataClass("a", 1), "note")],
            id="union nested in fixed tuple",
        ),
        pytest.param(
            '[{"foo": "a"}, {"name": "n"}]',
            [set[Union[_FooItem, _NamedItem]]],
            [{_FooItem("a"), _NamedItem("n")}],
            id="union nested in set",
        ),
        pytest.param(
            '{"item": {"name": "widget", "count": 3}}',
            [_NestedItem],
            [{"item": {"name": "widget", "count": 3}}],
            id="union nested in typed dict field",
        ),
        pytest.param(
            '{"items": [{"name": "w", "count": 3}], "note": "x"}',
            [_WrapperDataClass],
            [_WrapperDataClass(items=[{"name": "w", "count": 3}], note="x")],
            id="union nested in dataclass field",
        ),
        pytest.param(
            '{"id": "1", "name": "detailed"}',
            [Union[_BaseItem, _DetailedItem]],
            [{"id": "1", "name": "detailed"}],
            id="union prefers variant covering all keys",
        ),
        pytest.param(
            '{"id": "1"}',
            [Union[_BaseItem, _DetailedItem]],
            [{"id": "1"}],
            id="union narrower variant when keys match",
        ),
        pytest.param(
            '{"name": "w", "count": 3}',
            [Union[_OptionalItem, _ItemDict]],
            [{"name": "w", "count": 3}],
            id="union optional typed dict variant",
        ),
        pytest.param(
            '{"name": "w", "count": 3}',
            [Union[_TestDataClass, _ItemDict]],
            [{"name": "w", "count": 3}],
            id="union dataclass with defaults loses to covering variant",
        ),
        pytest.param(
            '{"name": "w", "count": 3, "extra": "ignored"}',
            [_ItemDict],
            [{"name": "w", "count": 3}],
            id="typed dict drops undeclared keys",
        ),
        pytest.param(
            '"hello"',
            [Union[str, _BaseItem, _DetailedItem]],
            ["hello"],
            id="union scalar variant",
        ),
        pytest.param(
            '{"id": "1"}',
            [Union[Annotated[str, "meta"], _BaseItem]],
            [{"id": "1"}],
            id="union skips annotated variant",
        ),
        pytest.param(
            '{"name": "widget"}',
            [_InheritedOptionalItem],
            [{"name": "widget"}],
            id="inherited optional keys",
        ),
        pytest.param(
            '{"name": "widget", "note": null}',
            [_NullableItem],
            [{"name": "widget", "note": None}],
            id="null kept for nullable optional",
        ),
        pytest.param(
            '{"name": "widget", "extra": null}',
            [_AnyNullItem],
            [{"name": "widget", "extra": None}],
            id="null kept for any typed optional",
        ),
        pytest.param(
            '{"name": "widget", "note": null}',
            [_MixedTotalItem],
            [{"name": "widget"}],
            id="null dropped for non-nullable optional in total false dict",
        ),
        pytest.param(
            '[{"name": "widget", "note": null}]',
            [list[_NullableItem]],
            [[{"name": "widget", "note": None}]],
            id="null canonicalized inside list",
        ),
        pytest.param(
            '{"item": {"name": "widget", "note": null}}',
            [dict[str, _NullableItem]],
            [{"item": {"name": "widget", "note": None}}],
            id="null canonicalized inside dict",
        ),
        pytest.param(
            '[{"name": "widget", "note": null}, "x"]',
            [tuple[_NullableItem, str]],
            [({"name": "widget", "note": None}, "x")],
            id="null canonicalized inside tuple",
        ),
        pytest.param(
            '{"name": "widget", "note": null}',
            [Optional[_NullableItem]],
            [{"name": "widget", "note": None}],
            id="null canonicalized inside optional",
        ),
    ],
)
def test_from_data_dict_like_unions_and_nulls(
    json: str, types: list[Any], expected: list[Any]
) -> None:
    converter = PydanticDataConverter()
    assert converter.from_data(Payload(data=json.encode()), types) == expected


@pytest.mark.parametrize(
    "json,types",
    [
        pytest.param('{"note": null}', [_NullableItem], id="missing required key"),
        pytest.param('{"name": null}', [_NullableItem], id="null for required key"),
        pytest.param(
            '[{"name": "widget", "note": 1}]',
            [list[_NullableItem]],
            id="wrong type for nullable optional",
        ),
        pytest.param("null", [_NullableItem], id="null for typed dict"),
        pytest.param(
            '[{"name": "widget"}]',
            [tuple[Union[_RequiredDataClass, _ItemDict], str]],
            id="fixed tuple arity mismatch",
        ),
        pytest.param(
            '{"other": true}',
            [Union[_RequiredDataClass, _ItemDict]],
            id="union no matching variant",
        ),
        pytest.param(
            '{"name": "w", "model": {"unexpected": 1}}',
            [_DictWithHookedField],
            id="model validation error propagates without retry",
        ),
    ],
)
def test_from_data_malformed_still_raises(json: str, types: list[Any]) -> None:
    converter = PydanticDataConverter()
    with pytest.raises((TypeError, ValueError)):
        converter.from_data(Payload(data=json.encode()), types)
