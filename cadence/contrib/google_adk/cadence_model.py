from __future__ import annotations

from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from pydantic import PrivateAttr

from cadence.contrib.google_adk.google_adk_activities import GoogleADKActivities


class CadenceModel(BaseLlm):
    _google_adk_activities: GoogleADKActivities = PrivateAttr(
        default_factory=GoogleADKActivities
    )

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if stream:
            raise RuntimeError("Streaming is not supported")

        responses = await self._google_adk_activities.generate_content_async(
            model_name=self.model,
            llm_request=llm_request,
        )
        for response in responses:
            yield response
