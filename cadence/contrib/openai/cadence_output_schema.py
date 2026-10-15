from dataclasses import dataclass
from typing import Any

from agents import AgentOutputSchemaBase


@dataclass
class CadenceOutputSchema(AgentOutputSchemaBase):
    """Serializable output schema metadata for a model Activity."""

    output_type_name: str
    plain_text: bool
    output_schema: dict[str, Any] | None
    strict_json_schema: bool

    def is_plain_text(self) -> bool:
        return self.plain_text

    def name(self) -> str:
        return self.output_type_name

    def json_schema(self) -> dict[str, Any]:
        if self.output_schema is None:
            raise ValueError("Plain-text output has no JSON schema")
        return self.output_schema

    def is_strict_json_schema(self) -> bool:
        return self.strict_json_schema

    def validate_json(self, json_str: str) -> Any:
        raise NotImplementedError(
            "Output validation runs in the workflow with the original schema"
        )


def to_cadence_output_schema(
    output_schema: AgentOutputSchemaBase | None,
) -> CadenceOutputSchema | None:
    if output_schema is None:
        return None
    plain_text = output_schema.is_plain_text()
    return CadenceOutputSchema(
        output_type_name=output_schema.name(),
        plain_text=plain_text,
        output_schema=None if plain_text else output_schema.json_schema(),
        strict_json_schema=output_schema.is_strict_json_schema(),
    )
