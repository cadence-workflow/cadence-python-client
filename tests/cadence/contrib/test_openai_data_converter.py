from typing import Type, cast

import pytest

pytest.importorskip("agents")

from agents import ModelResponse, TResponseInputItem  # noqa: E402
from agents.usage import Usage  # noqa: E402
from openai._models import construct_type  # noqa: E402
from openai.types.responses import Response  # noqa: E402

from cadence.contrib.pydantic import PydanticDataConverter  # noqa: E402

# OpenAIActivities.invoke_model input annotation
_MODEL_INPUT_TYPE = cast(Type, str | list[TResponseInputItem])


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("Hello", id="string"),
        pytest.param([{"role": "user", "content": "Hello"}], id="user message"),
        pytest.param(
            [{"type": "function_call_output", "call_id": "call-1", "output": "Hi"}],
            id="function call output",
        ),
    ],
)
def test_roundtrip_model_input(value: object) -> None:
    converter = PydanticDataConverter(exclude_unset=True)
    payload = converter.to_data([value])
    assert converter.from_data(payload, [_MODEL_INPUT_TYPE]) == [value]


def test_second_turn_model_input_after_model_response_roundtrip() -> None:
    # Parsed the way the OpenAI client parses a Responses API reply: only the
    # keys the API sent are in model_fields_set.
    response = cast(
        Response,
        construct_type(
            type_=Response,
            value={
                "id": "resp-1",
                "object": "response",
                "created_at": 0,
                "model": "gpt-4o",
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "greet",
                        "arguments": '{"name":"Ada"}',
                        "status": "completed",
                    }
                ],
            },
        ),
    )
    model_response = ModelResponse(
        output=response.output, usage=Usage(), response_id=response.id
    )
    converter = PydanticDataConverter(exclude_unset=True)

    # invoke_model result: encoded by the worker, decoded by the workflow
    decoded = converter.from_data(converter.to_data([model_response]), [ModelResponse])
    next_input = [
        {"role": "user", "content": "Hello"},
        *decoded[0].to_input_items(),
    ]
    assert decoded[0].to_input_items() == model_response.to_input_items()

    # next invoke_model input: encoded by the workflow, decoded by the worker
    payload = converter.to_data([next_input])
    assert converter.from_data(payload, [_MODEL_INPUT_TYPE]) == [next_input]
