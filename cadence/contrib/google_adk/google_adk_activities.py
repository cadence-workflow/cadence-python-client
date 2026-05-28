from __future__ import annotations

from google.adk.models import LLMRegistry
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from cadence import activity


class GoogleADKActivities:
    @activity.method
    async def generate_content_async(
        self,
        model_name: str,
        llm_request: LlmRequest,
    ) -> list[LlmResponse]:
        model = LLMRegistry.new_llm(model_name)
        responses: list[LlmResponse] = []
        async for response in model.generate_content_async(
            llm_request=llm_request,
            stream=False,
        ):
            responses.append(response)
        return responses
