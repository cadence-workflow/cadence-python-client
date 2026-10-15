from typing import Any, Type, cast
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

pytest.importorskip("agents")

from agents import (  # noqa: E402
    AgentOutputSchema,
    ModelResponse,
    ModelSettings,
    ModelTracing,
    TResponseInputItem,
)
from agents.usage import Usage  # noqa: E402
from openai._models import construct_type  # noqa: E402
from openai.types.responses import Response  # noqa: E402

from cadence._internal.fn_signature import FnSignature  # noqa: E402
from cadence.contrib.openai.cadence_model import CadenceModel  # noqa: E402
from cadence.contrib.openai.openai_activities import OpenAIActivities  # noqa: E402
from cadence.contrib.openai.cadence_output_schema import (  # noqa: E402
    CadenceOutputSchema,
    to_cadence_output_schema,
)
from cadence.contrib.pydantic import PydanticDataConverter  # noqa: E402

# OpenAIActivities.invoke_model input annotation
_MODEL_INPUT_TYPE = cast(Type, str | list[TResponseInputItem])


class _StructuredOutput(BaseModel):
    answer: str


def _invoke_model_arguments(output_schema: CadenceOutputSchema | None) -> list[Any]:
    return [
        "gpt-5-nano",
        None,
        "Hello",
        ModelSettings(),
        [],
        output_schema,
        [],
        ModelTracing.DISABLED,
        None,
        None,
        None,
    ]


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


def test_roundtrip_complete_invoke_model_arguments_with_null_output_schema() -> None:
    arguments = _invoke_model_arguments(None)
    signature = FnSignature.of(OpenAIActivities.invoke_model)
    converter = PydanticDataConverter(exclude_unset=True)

    decoded = signature.params_from_payload(converter, converter.to_data(arguments))

    assert len(signature.params) == 11
    assert decoded == arguments


def test_roundtrip_complete_invoke_model_arguments_with_structured_output() -> None:
    original = AgentOutputSchema(_StructuredOutput)
    transported = to_cadence_output_schema(original)
    assert transported is not None
    arguments = _invoke_model_arguments(transported)
    signature = FnSignature.of(OpenAIActivities.invoke_model)
    converter = PydanticDataConverter(exclude_unset=True)

    decoded = signature.params_from_payload(converter, converter.to_data(arguments))

    assert len(signature.params) == 11
    decoded_schema = decoded[5]
    assert isinstance(decoded_schema, CadenceOutputSchema)
    assert decoded_schema.name() == original.name()
    assert decoded_schema.is_plain_text() == original.is_plain_text()
    assert decoded_schema.json_schema() == original.json_schema()
    assert decoded_schema.is_strict_json_schema() == original.is_strict_json_schema()


@pytest.mark.asyncio
async def test_cadence_model_transports_structured_output_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    model = CadenceModel("gpt-5-nano")
    invoke_model = AsyncMock(
        return_value=ModelResponse(output=[], usage=Usage(), response_id=None)
    )
    setattr(model._openai_activities, "invoke_model", invoke_model)
    original = AgentOutputSchema(_StructuredOutput)

    await model.get_response(
        system_instructions=None,
        input="Hello",
        model_settings=ModelSettings(),
        tools=[],
        output_schema=original,
        handoffs=[],
        tracing=ModelTracing.DISABLED,
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
    )

    assert invoke_model.await_args is not None
    transported = invoke_model.await_args.kwargs["output_schema"]
    assert isinstance(transported, CadenceOutputSchema)
    assert transported.name() == original.name()
    assert transported.json_schema() == original.json_schema()


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
