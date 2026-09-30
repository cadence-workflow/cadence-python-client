"""Pydantic-native data converter for Cadence payloads."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import lru_cache
from json import JSONDecoder
from typing import Any

from pydantic import TypeAdapter
from pydantic_core import SchemaSerializer, core_schema

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DataConverter


class PydanticDataConverter(DataConverter):
    """Data converter using Pydantic's default serialization and validation.

    Pydantic serializes each value to JSON and validates each JSON value
    against its type hint through a cached :class:`pydantic.TypeAdapter`.
    Cadence's whitespace-delimited payload framing is retained. Missing
    values use the same defaults as
    :class:`~cadence.data_converter.DefaultDataConverter` (for example
    ``heartbeat_details`` on a first attempt).
    """

    def __init__(self, *, exclude_unset: bool = False) -> None:
        """Create the converter.

        Args:
            exclude_unset: Omit Pydantic model fields that were never set, so
                ``model_fields_set`` survives the round trip. Fields filled
                by a ``default_factory`` are not set and are regenerated on
                decode. The OpenAI Agents integration requires ``True``.
        """
        self._exclude_unset = exclude_unset
        self._decoder = JSONDecoder(strict=False)
        self._serializer = SchemaSerializer(core_schema.any_schema())
        self._type_adapter: Callable[[Any], TypeAdapter[Any]] = lru_cache(maxsize=1024)(
            TypeAdapter
        )

    def from_data(
        self, payload: Payload, type_hints: Sequence[type | None]
    ) -> list[Any]:
        if not payload.data:
            return [self._default_for(type_hint) for type_hint in type_hints]

        if not type_hints:
            type_hints = [None]

        results: list[Any] = []
        payload_str = payload.data.decode()
        start, end = 0, len(payload_str)
        while start < end and len(results) < len(type_hints):
            remaining = payload_str[start:end]
            value, value_end = self._decoder.raw_decode(remaining)
            type_hint = type_hints[len(results)]
            if type_hint and type_hint is not Any:
                value = self._type_adapter(type_hint).validate_json(
                    remaining[:value_end]
                )
            results.append(value)
            start += value_end + 1

        return results + [
            self._default_for(type_hint) for type_hint in type_hints[len(results) :]
        ]

    def to_data(self, values: list[Any]) -> Payload:
        return Payload(
            data=b" ".join(
                self._serializer.to_json(value, exclude_unset=self._exclude_unset)
                for value in values
            )
        )

    def _payload_value_count(self, payload: Payload, max_count: int) -> int:
        if not payload.data or max_count <= 0:
            return 0

        payload_str = payload.data.decode()
        count = 0
        start, end = 0, len(payload_str)
        while start < end and count < max_count:
            _, value_end = self._decoder.raw_decode(payload_str[start:end])
            start += value_end + 1
            count += 1

        return count

    @staticmethod
    def _default_for(type_hint: type | None) -> Any:
        if type_hint in (int, float):
            return 0
        if type_hint is bool:
            return False
        return None
