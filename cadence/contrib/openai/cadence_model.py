from typing import AsyncIterator
from agents import (
    Model,
    ModelSettings,
    TResponseInputItem,
    Tool,
    AgentOutputSchemaBase,
    Handoff,
    ModelTracing,
    ModelResponse,
)
from agents.items import TResponseStreamEvent
from openai.types.responses import ResponsePromptParam

from cadence.contrib.openai.cadence_tool import to_cadence_tool
from cadence.contrib.openai.openai_activities import OpenAIActivities


class CadenceModel(Model):
    def __init__(self, model_name: str):
        self._model_name = model_name
        self._openai_activities = OpenAIActivities()

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
        return await self._openai_activities.invoke_model(
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
