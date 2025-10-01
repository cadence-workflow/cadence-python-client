from abc import abstractmethod
from typing import Protocol, List, Type, Any

from cadence.api.v1.common_pb2 import Payload
from json import JSONDecoder
from msgspec import json, convert

_SPACE = ' '.encode()

class DataConverter(Protocol):

    @abstractmethod
    async def from_data(self, payload: Payload, type_hints: List[Type | None]) -> List[Any]:
        raise NotImplementedError()

    @abstractmethod
    async def to_data(self, values: List[Any]) -> Payload:
        raise NotImplementedError()

class DefaultDataConverter(DataConverter):
    def __init__(self) -> None:
        self._encoder = json.Encoder()
        # Need to use std lib decoder in order to decode the custom whitespace delimited data format
        self._decoder = JSONDecoder(strict=False)


    async def from_data(self, payload: Payload, type_hints: List[Type | None]) -> List[Any]:
        if not payload.data:
            return DefaultDataConverter._convert_into([], type_hints)

        payload_str = payload.data.decode()

        return self._decode_whitespace_delimited(payload_str, type_hints)

    def _decode_whitespace_delimited(self, payload: str, type_hints: List[Type | None]) -> List[Any]:
        results: List[Any] = []
        start, end = 0, len(payload)
        while start < end and len(results) < len(type_hints):
            remaining = payload[start:end]
            (value, value_end) = self._decoder.raw_decode(remaining)
            start += value_end + 1
            results.append(value)

        return DefaultDataConverter._convert_into(results, type_hints)

    @staticmethod
    def _convert_into(values: List[Any], type_hints: List[Type | None]) -> List[Any]:
        results: List[Any] = []
        for i, type_hint in enumerate(type_hints):
            if not type_hint:
                value = values[i]
            elif i < len(values):
                value = convert(values[i], type_hint)
            else:
                value = DefaultDataConverter._get_default(type_hint)

            results.append(value)

        return results

    @staticmethod
    def _get_default(type_hint: Type) -> Any:
        if type_hint in (int, float):
            return 0
        if type_hint is bool:
            return False
        return None


    async def to_data(self, values: List[Any]) -> Payload:
        result = bytearray()
        for index, value in enumerate(values):
            self._encoder.encode_into(value, result, -1)
            if index < len(values) - 1:
                result += _SPACE

        return Payload(data=bytes(result))

