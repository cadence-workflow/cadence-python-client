from agents import Model, OpenAIProvider
from openai import AsyncOpenAI
from openai.types.responses import ResponsePromptParam
from cadence import activity
from agents import (
    TResponseInputItem,
    ModelSettings,
    AgentOutputSchemaBase,
    Handoff,
    ModelTracing,
    ModelResponse,
)

from cadence.contrib.openai.cadence_tool import CadenceTool, from_cadence_tool


class OpenAIActivities:
    def __init__(self):
        self._openai_provider: OpenAIProvider = OpenAIProvider(
            openai_client=AsyncOpenAI(max_retries=0)
        )

    @activity.method
    async def invoke_model(
        self,
        model_name: str,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[CadenceTool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:

        model: Model = self._openai_provider.get_model(model_name)
        return await model.get_response(
            system_instructions=system_instructions,
            input=input,
            model_settings=model_settings,
            tools=[from_cadence_tool(tool) for tool in tools],
            output_schema=output_schema,
            handoffs=handoffs,
            tracing=tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )
