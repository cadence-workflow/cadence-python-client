from abc import abstractmethod
from typing import Protocol, List, Type, Any

from cadence.api.v1.common_pb2 import Payload
from json import JSONDecoder
from msgspec import json, convert


class DataConverter(Protocol):

    @abstractmethod
    async def from_data(self, payload: Payload, type_hints: List[Type]) -> List[Any]:
        raise NotImplementedError()

    @abstractmethod
    async def to_data(self, values: List[Any]) -> Payload:
        raise NotImplementedError()

class DefaultDataConverter(DataConverter):
    def __init__(self) -> None:
        self._encoder = json.Encoder()
        self._decoder = json.Decoder()
        self._fallback_decoder = JSONDecoder(strict=False)


    async def from_data(self, payload: Payload, type_hints: List[Type]) -> List[Any]:
        if len(type_hints) > 1:
            payload_str = payload.data.decode()
            # Handle payloads from the Go client, which are a series of json objects rather than a json array
            if not payload_str.startswith("["):
                return self._decode_whitespace_delimited(payload_str, type_hints)
            else:
                as_list = self._decoder.decode(payload_str)
                return DefaultDataConverter._convert_into(as_list, type_hints)

        as_value = self._decoder.decode(payload.data)
        return DefaultDataConverter._convert_into([as_value], type_hints)


    def _decode_whitespace_delimited(self, payload: str, type_hints: List[Type]) -> List[Any]:
        results: List[Any] = []
        start, end = 0, len(payload)
        while start < end and len(results) < len(type_hints):
            remaining = payload[start:end]
            (value, value_end) = self._fallback_decoder.raw_decode(remaining)
            start += value_end + 1
            results.append(value)

        return DefaultDataConverter._convert_into(results, type_hints)

    @staticmethod
    def _convert_into(values: List[Any], type_hints: List[Type]) -> List[Any]:
        results: List[Any] = []
        for i, type_hint in enumerate(type_hints):
            if i < len(values):
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
        data_value = values
        # Don't wrap single values in a json array
        if len(values) == 1:
            data_value = values[0]

        return Payload(data=self._encoder.encode(data_value))

