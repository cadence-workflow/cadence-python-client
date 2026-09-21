import json
from datetime import timedelta
from typing import Any

import pytest

try:
    import httpx
    from agents import Agent, RunConfig, Runner, function_tool
    from openai import AsyncOpenAI
except ModuleNotFoundError:
    pytest.skip("OpenAI dependencies are not installed", allow_module_level=True)

import cadence
import cadence.contrib.openai.openai_activities as openai_activities_module
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import GetWorkflowExecutionHistoryRequest
from cadence.client import ClientOptions
from cadence.contrib.openai import OpenAIActivities, PydanticDataConverter
from cadence.worker import Worker
from tests.integration_tests.helper import CadenceHelper

_WORKFLOW = "OpenAIModelToolModelWorkflow"
_FINAL_ANSWER = "Done."
_registry = cadence.Registry()


@_registry.activity(name="greet")
async def greet(name: str) -> str:
    """Return a fixed greeting."""
    return f"Hello, {name}."


@_registry.workflow(name=_WORKFLOW)
class _ModelToolModelWorkflow:
    @cadence.workflow.run
    async def run(self, user_input: str) -> str:
        agent = Agent(
            name="test_agent",
            model="scripted-model",
            tools=[function_tool(greet)],
        )
        result = await Runner.run(
            agent,
            user_input,
            run_config=RunConfig(tracing_disabled=True),
        )
        return str(result.final_output)


def _response(request: dict[str, Any], call_number: int) -> dict[str, Any]:
    common = {
        "created_at": 0,
        "model": request["model"],
        "object": "response",
        "parallel_tool_calls": False,
        "status": "completed",
        "tool_choice": "auto",
        "tools": request.get("tools", []),
    }
    if call_number == 1:
        return {
            **common,
            "id": "tool-response",
            "output": [
                {
                    "arguments": '{"name":"Ada"}',
                    "call_id": "call-1",
                    "name": "greet",
                    "status": "completed",
                    "type": "function_call",
                }
            ],
        }
    return {
        **common,
        "id": "final-response",
        "output": [
            {
                "content": [
                    {
                        "annotations": [],
                        "text": _FINAL_ANSWER,
                        "type": "output_text",
                    }
                ],
                "id": "message-1",
                "role": "assistant",
                "status": "completed",
                "type": "message",
            }
        ],
    }


async def test_model_tool_model_workflow(
    helper: CadenceHelper, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[dict[str, Any]] = []

    async def handle_request(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=_response(body, len(requests)))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
    openai_client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        http_client=http_client,
        max_retries=0,
    )
    monkeypatch.setattr(
        openai_activities_module,
        "AsyncOpenAI",
        lambda **_kwargs: openai_client,
    )

    registry = cadence.Registry.of(_registry)
    registry.register_activities(OpenAIActivities())
    options: ClientOptions = {
        **helper.options,
        "data_converter": PydanticDataConverter(),
    }
    task_list = f"m0-openai-173-{helper.test_name}"

    try:
        async with cadence.Client(**options) as client:
            async with Worker(client, task_list, registry):
                execution = await client.start_workflow(
                    _WORKFLOW,
                    "Call the greeting tool.",
                    task_list=task_list,
                    execution_start_to_close_timeout=timedelta(seconds=30),
                )
                close_history = await client.workflow_stub.GetWorkflowExecutionHistory(
                    GetWorkflowExecutionHistoryRequest(
                        domain=client.domain,
                        workflow_execution=execution,
                        wait_for_new_event=True,
                        history_event_filter_type=(
                            EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT
                        ),
                        skip_archival=True,
                    )
                )
                history = await client.workflow_stub.GetWorkflowExecutionHistory(
                    GetWorkflowExecutionHistoryRequest(
                        domain=client.domain,
                        workflow_execution=execution,
                        skip_archival=True,
                    )
                )
    finally:
        await openai_client.close()

    close_event = close_history.history.events[-1]
    assert close_event.HasField("workflow_execution_completed_event_attributes"), (
        close_event
    )
    result = close_event.workflow_execution_completed_event_attributes.result
    assert PydanticDataConverter().from_data(result, [str]) == [_FINAL_ANSWER]
    activity_types = [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]
    assert activity_types == [
        "OpenAIActivities.invoke_model",
        "greet",
        "OpenAIActivities.invoke_model",
    ]
    assert len(requests) == 2
