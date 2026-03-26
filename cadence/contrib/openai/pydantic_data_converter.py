import dataclasses
import datetime as dt
import enum
import json as json_module
import logging
from json import JSONDecoder
from typing import Any, List, Sequence, Type

from pydantic import BaseModel, TypeAdapter

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DataConverter

_SPACE = b" "
_SENTINEL = object()

logger = logging.getLogger(__name__)


class PydanticDataConverter(DataConverter):
    """DataConverter that handles Pydantic BaseModel and TypedDict types
    (e.g. ResponseInputItemParam) via Pydantic's TypeAdapter."""

    def __init__(self) -> None:
        self._decoder = JSONDecoder(strict=False)
        self._adapter_cache: dict[Any, TypeAdapter[Any] | None] = {}

    def _get_adapter(self, type_hint: Any) -> TypeAdapter[Any] | None:
        cached = self._adapter_cache.get(type_hint, _SENTINEL)
        if cached is not _SENTINEL:
            return cached  # type: ignore[return-value]
        try:
            adapter: TypeAdapter[Any] | None = TypeAdapter(type_hint)
        except Exception:
            logger.debug("TypeAdapter failed for %s, will use raw values", type_hint)
            adapter = None
        self._adapter_cache[type_hint] = adapter
        return adapter

    def from_data(
        self, payload: Payload, type_hints: Sequence[Type | None]
    ) -> List[Any]:
        if not payload.data:
            return [_get_default(th) for th in type_hints]

        raw_values = self._decode_whitespace_delimited(
            payload.data.decode(), len(type_hints)
        )

        results: List[Any] = []
        for i, type_hint in enumerate(type_hints):
            if i >= len(raw_values):
                results.append(_get_default(type_hint))
            elif type_hint is None or type_hint is Any:
                results.append(raw_values[i])
            else:
                adapter = self._get_adapter(type_hint)
                if adapter is None:
                    results.append(raw_values[i])
                else:
                    try:
                        results.append(adapter.validate_python(raw_values[i]))
                    except Exception:
                        results.append(raw_values[i])

        return results

    def _decode_whitespace_delimited(self, payload: str, max_count: int) -> List[Any]:
        results: List[Any] = []
        start, end = 0, len(payload)
        while start < end and len(results) < max_count:
            remaining = payload[start:end]
            value, value_end = self._decoder.raw_decode(remaining)
            start += value_end + 1
            results.append(value)
        return results

    def to_data(self, values: List[Any]) -> Payload:
        result = bytearray()
        for index, value in enumerate(values):
            result += _serialize_value(value)
            if index < len(values) - 1:
                result += _SPACE
        return Payload(data=bytes(result))


def _serialize_value(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        return value.model_dump_json().encode()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_module.dumps(
            dataclasses.asdict(value), separators=(",", ":"), default=_json_default
        ).encode()
    if isinstance(value, list):
        parts = [_to_json_compatible(item) for item in value]
        return json_module.dumps(
            parts, separators=(",", ":"), default=_json_default
        ).encode()
    return json_module.dumps(
        value, separators=(",", ":"), default=_json_default
    ).encode()


def _to_json_compatible(obj: Any) -> Any:
    """Recursively convert an object to a JSON-compatible structure."""
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    if isinstance(obj, dt.timedelta):
        return obj.total_seconds()
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, enum.Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return {k: _to_json_compatible(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_compatible(item) for item in obj]
    if isinstance(obj, set):
        return sorted(_to_json_compatible(item) for item in obj)
    return obj


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    if isinstance(obj, dt.timedelta):
        return obj.total_seconds()
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _get_default(type_hint: Type | None) -> Any:
    if type_hint is None:
        return None
    if type_hint in (int, float):
        return 0
    if type_hint is bool:
        return False
    return None
