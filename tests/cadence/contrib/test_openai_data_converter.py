from typing import Type, cast

import pytest

try:
    from agents import TResponseInputItem
except ModuleNotFoundError:
    pytest.skip("OpenAI dependencies are not installed", allow_module_level=True)

from cadence.contrib.pydantic import PydanticDataConverter


_MODEL_INPUT_TYPE = cast(Type, str | list[TResponseInputItem])


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
        [
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
        ],
    ],
)
def test_roundtrip_openai_model_input(value: object) -> None:
    converter = PydanticDataConverter()

    payload = converter.to_data([value])

    assert converter.from_data(payload, [_MODEL_INPUT_TYPE]) == [value]


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
def test_openai_model_input_rejects_malformed_value(value: object) -> None:
    converter = PydanticDataConverter()
    payload = converter.to_data([value])

    with pytest.raises(ValueError):
        converter.from_data(payload, [_MODEL_INPUT_TYPE])
