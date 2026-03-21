from dataclasses import dataclass
from typing import Any, AsyncIterator, Required, Union, Unpack
from agents import FunctionTool, Model, ModelSettings, OpenAIProvider, RunContextWrapper, TResponseInputItem, Tool, AgentOutputSchemaBase, Handoff, ModelTracing, ModelResponse
from agents.items import TResponseStreamEvent
from agents.tool_context import ToolContext
from openai import AsyncOpenAI
from openai.types.responses import ResponsePromptParam

from cadence import activity, workflow
from contrib.openai.cadence_tool import to_cadence_tool
from contrib.openai.openai_activities import OpenAIActivities


class CadenceModel(Model):
    def __init__(self, model_name: str):
        self._model_name = model_name

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:
        """
        run model inside cadence activity
        """
        return await OpenAIActivities().invoke_model(
            model_name=self._model_name,
            system_instructions=system_instructions,
            input=input,
            model_settings=model_settings,
            tools=[to_cadence_tool(tool) for tool in tools],
            output_schema=output_schema,
            handoffs=handoffs,
            tracing=tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> AsyncIterator[TResponseStreamEvent]:
        raise RuntimeError("Model stream_response is not yet supported.")
