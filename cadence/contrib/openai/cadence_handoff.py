from dataclasses import dataclass
from typing import Any

from agents import Handoff
from agents.run_context import RunContextWrapper
from typing import Awaitable


@dataclass
class CadenceHandoff:
    """Serializable representation of a Handoff for crossing the Cadence activity boundary.
    Only the fields needed by the model (tool schema) are kept; callable/runtime
    fields are reconstructed with no-op stubs on the activity side."""

    tool_name: str
    tool_description: str
    input_json_schema: dict[str, Any]
    agent_name: str
    strict_json_schema: bool = True


def to_cadence_handoff(handoff: Handoff[Any, Any]) -> CadenceHandoff:
    return CadenceHandoff(
        tool_name=handoff.tool_name,
        tool_description=handoff.tool_description,
        input_json_schema=handoff.input_json_schema,
        agent_name=handoff.agent_name,
        strict_json_schema=handoff.strict_json_schema,
    )


def from_cadence_handoff(ch: CadenceHandoff) -> Handoff[Any, Any]:
    async def noop_invoke(_ctx: RunContextWrapper[Any], _json: str):
        raise RuntimeError("Handoff invocation is handled by the runner, not the model")

    return Handoff(
        tool_name=ch.tool_name,
        tool_description=ch.tool_description,
        input_json_schema=ch.input_json_schema,
        on_invoke_handoff=noop_invoke,
        agent_name=ch.agent_name,
        strict_json_schema=ch.strict_json_schema,
    )
