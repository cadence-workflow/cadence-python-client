"""
Search Attributes support for Cadence workflows.

Search attributes are custom indexed fields attached to workflow executions
that enable advanced visibility queries using SQL-like syntax.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from cadence.api.v1.common_pb2 import Payload, SearchAttributes

# Supported Python types for search attribute values (any JSON-serializable type)
SearchAttributeValue = Any

# CadenceChangeVersion is used as search attributes key to find workflows with specific change version.
CADENCE_CHANGE_VERSION = "CadenceChangeVersion"


class SearchAttributeConverter:
    """
    Converts between Python dictionaries and protobuf SearchAttributes.
    """

    def encode(self, attrs: dict[str, SearchAttributeValue]) -> SearchAttributes:
        """
        Encode a Python dictionary to a protobuf SearchAttributes message.

        Args:
            attrs: Dictionary mapping attribute names to Python values

        Returns:
            SearchAttributes protobuf message

        Raises:
            ValueError: If attrs is empty or contains unsupported types
        """
        if not attrs:
            raise ValueError("search attributes is empty")

        result = SearchAttributes()

        for key, value in attrs.items():
            try:
                encoded_bytes = self._encode_value(value)
                result.indexed_fields[key].CopyFrom(Payload(data=encoded_bytes))
            except (TypeError, ValueError) as e:
                raise ValueError(f"encode search attribute [{key}] error: {e}") from e

        return result

    def decode(
        self,
        attrs: SearchAttributes,
        type_hints: dict[str, type] | None = None,
    ) -> dict[str, Any]:
        """
        Decode a protobuf SearchAttributes message to a Python dictionary.

        Args:
            attrs: SearchAttributes protobuf message
            type_hints: Optional type hints for datetime conversion

        Returns:
            Dictionary mapping attribute names to decoded values
        """
        if not attrs.indexed_fields:
            return {}

        type_hints = type_hints or {}
        result: dict[str, Any] = {}

        for key, payload in attrs.indexed_fields.items():
            hint = type_hints.get(key)
            result[key] = self._decode_value(payload.data, hint)

        return result

    def _encode_value(self, value: SearchAttributeValue) -> bytes:
        """Encode a single value to JSON bytes."""
        if isinstance(value, datetime):
            return json.dumps(value.isoformat()).encode("utf-8")
        else:
            return json.dumps(value).encode("utf-8")

    def _decode_value(self, data: bytes, type_hint: type | None = None) -> Any:
        """Decode JSON bytes to a Python value."""
        if not data:
            return None

        raw_value = json.loads(data.decode("utf-8"))

        if type_hint is datetime and isinstance(raw_value, str):
            return datetime.fromisoformat(raw_value)

        return raw_value


def validate_search_attributes(
    attrs: dict[str, SearchAttributeValue],
    allow_reserved_keys: bool = False,
) -> None:
    """
    Validate search attributes before encoding.

    Raises:
        ValueError: If empty or uses reserved keys
    """
    if not attrs:
        raise ValueError("search attributes is empty")

    if not allow_reserved_keys and CADENCE_CHANGE_VERSION in attrs:
        raise ValueError(
            f"{CADENCE_CHANGE_VERSION} is a reserved key that cannot be set, "
            "please use other key"
        )
