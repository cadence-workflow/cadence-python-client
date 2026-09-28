"""Pydantic-native data converter for Cadence payloads."""

from __future__ import annotations

from json import JSONDecoder
from typing import Any, List, Sequence, Type

from pydantic import TypeAdapter
from pydantic_core import to_json

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DataConverter


class PydanticDataConverter(DataConverter):
    """Data converter using Pydantic's default serialization and validation.

    Pydantic serializes each value to JSON and validates decoded JSON values
    against their type hints. Cadence's whitespace-delimited payload framing
    is retained.
    """

    def __init__(self) -> None:
        self._decoder = JSONDecoder(strict=False)

    def from_data(
        self, payload: Payload, type_hints: List[Type | None]
    ) -> List[Any]:
        if not payload.data:
            return []

        if not type_hints:
            type_hints = [None]

        return self._decode_whitespace_delimited(payload.data.decode(), type_hints)

    def _decode_whitespace_delimited(
        self,
        payload: str,
        type_hints: Sequence[Type | None],
    ) -> List[Any]:
        results: List[Any] = []
        start, end = 0, len(payload)
        while start < end and len(results) < len(type_hints):
            remaining = payload[start:end]
            value, value_end = self._decoder.raw_decode(remaining)
            type_hint = type_hints[len(results)]
            if type_hint and type_hint is not Any:
                value = TypeAdapter(type_hint).validate_json(remaining[:value_end])
            results.append(value)
            start += value_end + 1

        return results

    def to_data(self, values: List[Any]) -> Payload:
        return Payload(data=b" ".join(to_json(value) for value in values))
