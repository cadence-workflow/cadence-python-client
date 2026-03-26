from dataclasses import dataclass
from typing import Any, Union

from agents import FunctionTool, Tool
from agents.tool_context import ToolContext


@dataclass
class CadenceFunctionTool:
    """
    CadenceFunctionTool is a serializable presentation of a function tool.
    """

    name: str
    description: str
    params_json_schema: dict[str, Any]
    strict_json_schema: bool = True
    is_enabled: bool = True


"""CadenceTool is a union of all the tool types that can be used with Cadence."""
CadenceTool = Union[CadenceFunctionTool]


def to_cadence_tool(tool: Tool) -> CadenceTool:
    if isinstance(tool, FunctionTool):
        if not isinstance(tool.is_enabled, bool):
            raise ValueError("is_enabled must be a bool")

        return CadenceFunctionTool(
            name=tool.name,
            description=tool.description,
            params_json_schema=tool.params_json_schema,
            strict_json_schema=tool.strict_json_schema,
            is_enabled=tool.is_enabled,
        )
    raise ValueError(f"Unknown tool type: {type(tool)}")


def from_cadence_tool(tool: CadenceTool) -> Tool:
    if isinstance(tool, CadenceFunctionTool):

        async def noop_on_invoke_tool(_ctx: ToolContext[Any], _input: str) -> str:
            return ""

        return FunctionTool(
            name=tool.name,
            description=tool.description,
            params_json_schema=tool.params_json_schema,
            strict_json_schema=tool.strict_json_schema,
            is_enabled=tool.is_enabled,
            on_invoke_tool=noop_on_invoke_tool,
        )
    raise ValueError(f"Unknown tool type: {type(tool)}")
