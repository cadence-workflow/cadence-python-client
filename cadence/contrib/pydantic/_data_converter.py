"""Pydantic-native data converter for Cadence payloads."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, List, Sequence, Type

from pydantic import TypeAdapter
from pydantic_core import SchemaSerializer, core_schema

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DefaultDataConverter


class PydanticDataConverter(DefaultDataConverter):
    """Data converter using Pydantic's default serialization and validation.

    Pydantic serializes each value to JSON and validates each JSON value
    against its type hint through a cached :class:`pydantic.TypeAdapter`.
    Cadence's whitespace-delimited payload framing and the defaults for
    missing values are inherited from
    :class:`~cadence.data_converter.DefaultDataConverter`.
    """

    def __init__(self, *, exclude_unset: bool = False) -> None:
        """Create the converter.

        Args:
            exclude_unset: Omit Pydantic model fields that were never set, so
                ``model_fields_set`` survives the round trip. Fields filled
                by a ``default_factory`` are not set and are regenerated on
                decode. The OpenAI Agents integration requires ``True``.
        """
        super().__init__()
        self._exclude_unset = exclude_unset
        self._serializer = SchemaSerializer(core_schema.any_schema())
        self._type_adapter: Callable[[Any], TypeAdapter[Any]] = lru_cache(maxsize=1024)(
            TypeAdapter
        )

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
                value = self._type_adapter(type_hint).validate_json(
                    remaining[:value_end]
                )
            results.append(value)
            start += value_end + 1

        return results + [
            self._get_default(type_hint) for type_hint in type_hints[len(results) :]
        ]

    def to_data(self, values: List[Any]) -> Payload:
        return Payload(
            data=b" ".join(
                self._serializer.to_json(value, exclude_unset=self._exclude_unset)
                for value in values
            )
        )
