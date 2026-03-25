import sys

from .openai_activities import OpenAIActivities
from .cadence_agent_runner import CadenceAgentRunner as _CadenceAgentRunner  # noqa: F401 — imported for side effect
from .pydantic_data_converter import PydanticDataConverter

if sys.version_info < (3, 12):
    raise ImportError(
        "The 'openai' module requires Python 3.12 or higher due to its dependency on inspect.markcoroutinefunction"
    )

__all__ = [
    PydanticDataConverter,
    OpenAIActivities,
]
