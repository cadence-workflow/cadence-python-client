from typing import Type, cast

import pytest

try:
    from agents import TResponseInputItem
except ModuleNotFoundError:
    pytest.skip("OpenAI dependencies are not installed", allow_module_level=True)

from cadence.contrib.pydantic import PydanticDataConverter
from cadence.data_converter import DefaultDataConverter


_MODEL_INPUT_TYPE = cast(Type, str | list[TResponseInputItem])


@pytest.fixture(params=[PydanticDataConverter], ids=["pydantic"])
def converter(request: pytest.FixtureRequest) -> DefaultDataConverter:
    converter_type = cast(type[DefaultDataConverter], request.param)
    return converter_type()


def test_default_converter_cannot_decode_openai_input() -> None:
    # str | list[TResponseInputItem] nests unions of TypedDicts, which
    # msgspec cannot schema-compile (msgspec#982). The OpenAI integration
    # requires PydanticDataConverter.
    converter = DefaultDataConverter()
    payload = converter.to_data([[{"role": "user", "content": "hi"}]])
    with pytest.raises(TypeError):
        converter.from_data(payload, [_MODEL_INPUT_TYPE])


@pytest.mark.parametrize(
    "value",
    [
        "Hello",
        [{"role": "user", "content": "Hello"}],
        [
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "Hello",
            }
        ],
    ],
)
def test_roundtrip_openai_model_input(
    converter: DefaultDataConverter, value: object
) -> None:
    payload = converter.to_data([value])

    assert converter.from_data(payload, [_MODEL_INPUT_TYPE]) == [value]


def test_roundtrip_openai_second_turn_canonicalizes_optional_nulls(
    converter: DefaultDataConverter,
) -> None:
    value = [
        {"role": "user", "content": "Hello"},
        {
            "type": "function_call",
            "arguments": '{"name":"Ada"}',
            "call_id": "call-1",
            "name": "greet",
            "id": None,
            "namespace": None,
            "status": "completed",
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "Hello",
        },
    ]
    payload = converter.to_data([value])

    assert converter.from_data(payload, [_MODEL_INPUT_TYPE]) == [
        [
            {"role": "user", "content": "Hello"},
            {
                "type": "function_call",
                "arguments": '{"name":"Ada"}',
                "call_id": "call-1",
                "name": "greet",
                "status": "completed",
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "Hello",
            },
        ]
    ]


@pytest.mark.parametrize(
    "value",
    [
        [{"type": "function_call_output"}],
        [
            {
                "type": "function_call_output",
                "call_id": None,
                "output": "Hello",
            }
        ],
        [
            {
                "type": "function_call",
                "arguments": '{"name":"Ada"}',
                "call_id": "call-1",
                "name": None,
                "id": None,
                "namespace": None,
            }
        ],
    ],
)
def test_openai_model_input_rejects_malformed_value(
    converter: DefaultDataConverter, value: object
) -> None:
    payload = converter.to_data([value])

    with pytest.raises((TypeError, ValueError)):
        converter.from_data(payload, [_MODEL_INPUT_TYPE])
