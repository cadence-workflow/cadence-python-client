import dataclasses
import enum
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional, Type, TypedDict

import pytest
from pydantic import BaseModel

from msgspec import ValidationError

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
