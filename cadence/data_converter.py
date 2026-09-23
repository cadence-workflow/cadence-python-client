import dataclasses
from abc import abstractmethod
from functools import lru_cache
from types import UnionType
from typing import (
    Annotated,
    Any,
    Callable,
    List,
    NotRequired,
    Protocol,
    Required,
    Sequence,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from cadence.api.v1.common_pb2 import Payload
from json import JSONDecoder
from msgspec import ValidationError, convert, json
from typing_extensions import is_typeddict

_SPACE = " ".encode()
EncHook = Callable[[Any], Any]
DecHook = Callable[[Any, Any], Any]

_UNWRAPPED_ORIGINS = (Annotated, Required, NotRequired)


def _unwrap(type_hint: Any) -> Any:
    while get_origin(type_hint) in _UNWRAPPED_ORIGINS:
        type_hint = get_args(type_hint)[0]
    return type_hint


def _allows_none(type_hint: Any) -> bool:
    hint = _unwrap(type_hint)
    if hint is None or hint is type(None) or hint is Any:
        return True
    return get_origin(hint) in (Union, UnionType) and any(
        arg is type(None) for arg in get_args(hint)
    )


def _contains_typed_dict(type_hint: Any, seen: frozenset[int] = frozenset()) -> bool:
    if is_typeddict(type_hint):
        return True
    if id(type_hint) in seen:
        return False
    seen = seen | {id(type_hint)}
    return any(_contains_typed_dict(arg, seen) for arg in get_args(type_hint))


def _contains_none(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_contains_none(item) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_none(item) for item in value)
    return False


@lru_cache(maxsize=1024)
def _typed_dict_info(type_hint: Any) -> tuple[dict[str, Any], set[str]]:
    field_hints = get_type_hints(type_hint, include_extras=True)
    required_keys = set(type_hint.__required_keys__)
    for key, field_hint in field_hints.items():
        origin = get_origin(field_hint)
        if origin is Required:
            required_keys.add(key)
        elif origin is NotRequired:
            required_keys.discard(key)
    return field_hints, required_keys


@lru_cache(maxsize=1024)
def _dataclass_info(type_hint: Any) -> tuple[dict[str, Any], frozenset[str]]:
    field_hints = get_type_hints(type_hint, include_extras=True)
    field_names = frozenset(field.name for field in dataclasses.fields(type_hint))
    return field_hints, field_names


class DataConverter(Protocol):
    @abstractmethod
    def from_data(self, payload: Payload, type_hints: List[Type | None]) -> List[Any]:
        raise NotImplementedError()

    @abstractmethod
    def to_data(self, values: List[Any]) -> Payload:
        raise NotImplementedError()


class DefaultDataConverter(DataConverter):
    def __init__(
        self,
        *,
        enc_hook: EncHook | None = None,
        dec_hook: DecHook | None = None,
    ) -> None:
        self._dec_hook = dec_hook
        self._encoder = (
            json.Encoder(enc_hook=enc_hook) if enc_hook is not None else json.Encoder()
        )
        # Need to use std lib decoder in order to decode the custom whitespace delimited data format
        self._decoder = JSONDecoder(strict=False)

    def from_data(
        self, payload: Payload, type_hints: Sequence[Type | None]
    ) -> List[Any]:
        if not payload.data:
            return self._convert_into([], type_hints)

        if not type_hints:
            type_hints = [None]

        payload_str = payload.data.decode()

        return self._decode_whitespace_delimited(payload_str, type_hints)

    def _decode_whitespace_delimited(
        self, payload: str, type_hints: Sequence[Type | None]
    ) -> List[Any]:
        results: List[Any] = []
        start, end = 0, len(payload)
        while start < end and len(results) < len(type_hints):
            remaining = payload[start:end]
            (value, value_end) = self._decoder.raw_decode(remaining)
            start += value_end + 1
            results.append(value)

        return self._convert_into(results, type_hints)

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

    def _convert_into(
        self, values: List[Any], type_hints: Sequence[Type | None]
    ) -> List[Any]:
        results: List[Any] = []
        for i, type_hint in enumerate(type_hints):
            if i < len(values):
                value = values[i]
                if type_hint and type_hint is not Any:
                    value = self._convert_value(value, type_hint)
            else:
                value = DefaultDataConverter._get_default(type_hint)
            results.append(value)
        return results

    def _convert_value(self, value: Any, type_hint: Any) -> Any:
        try:
            return convert(value, type_hint, dec_hook=self._dec_hook)
        except TypeError:
            # msgspec cannot schema-compile unions of multiple dict-like types
            # (dataclass, TypedDict, Struct, dict). Walk the hint instead.
            return self._convert_structured(value, type_hint)
        except ValidationError:
            # The only failure the walk can repair is an explicit null on a
            # non-nullable optional TypedDict key. Retry only when a null is
            # actually present in the payload; anything else is a real
            # validation failure (including dec_hook errors, which msgspec
            # wraps as ValidationError) that must not run twice.
            if _contains_typed_dict(type_hint) and _contains_none(value):
                return self._convert_structured(value, type_hint)
            raise

    def _convert_structured(self, value: Any, type_hint: Any) -> Any:
        if is_typeddict(type_hint) and isinstance(value, dict):
            return self._convert_typed_dict(value, type_hint)

        origin = get_origin(type_hint)
        args = get_args(type_hint)
        if origin is Annotated or origin in (Required, NotRequired):
            return self._convert_value(value, args[0])
        if origin is Union or origin is UnionType:
            return self._convert_union(value, args)
        if origin is list and isinstance(value, list):
            item_hint = args[0] if args else Any
            return [self._convert_value(item, item_hint) for item in value]
        if origin in (set, frozenset) and isinstance(value, (list, tuple)):
            item_hint = args[0] if args else Any
            return origin(self._convert_value(item, item_hint) for item in value)
        if origin is tuple and isinstance(value, (list, tuple)):
            return self._convert_tuple(value, args)
        if origin is dict and isinstance(value, dict):
            key_hint, value_hint = args if len(args) == 2 else (Any, Any)
            return {
                self._convert_value(key, key_hint): self._convert_value(
                    item, value_hint
                )
                for key, item in value.items()
            }
        if (
            isinstance(type_hint, type)
            and dataclasses.is_dataclass(type_hint)
            and isinstance(value, dict)
        ):
            return self._convert_dataclass(value, type_hint)
        # The hint has no dict-like shape to walk, so let msgspec report it.
        return convert(value, type_hint, dec_hook=self._dec_hook)

    @staticmethod
    def _covers(variant: Any, keys: Any) -> bool:
        while get_origin(variant) is Annotated:
            variant = get_args(variant)[0]
        if is_typeddict(variant):
            return set(keys) <= _typed_dict_info(variant)[0].keys()
        if isinstance(variant, type) and dataclasses.is_dataclass(variant):
            return set(keys) <= _dataclass_info(variant)[1]
        return True

    def _convert_union(self, value: Any, variants: tuple[Any, ...]) -> Any:
        if value is None and any(variant is type(None) for variant in variants):
            return None

        errors: list[Exception] = []
        candidates = [variant for variant in variants if variant is not type(None)]
        if isinstance(value, dict):
            candidates.sort(key=lambda variant: not self._covers(variant, value.keys()))
        for variant in candidates:
            try:
                # A TypedDict variant is walked directly so canonicalization
                # runs in one pass instead of a doomed msgspec attempt plus
                # the fallback walk.
                if is_typeddict(variant) and isinstance(value, dict):
                    return self._convert_typed_dict(value, variant)
                return self._convert_value(value, variant)
            except Exception as exc:
                # A custom dec_hook may reject a variant with an exception
                # other than TypeError. Keep trying until a variant succeeds.
                errors.append(exc)

        raise TypeError(
            f"Unable to convert value into any union variant {variants}"
        ) from (errors[-1] if errors else None)

    def _convert_tuple(
        self, value: list[Any] | tuple[Any, ...], args: tuple[Any, ...]
    ) -> tuple[Any, ...]:
        if not args:
            return tuple(value)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(self._convert_value(item, args[0]) for item in value)
        if len(value) != len(args):
            raise TypeError(f"Expected tuple of length {len(args)}, got {len(value)}")
        return tuple(
            self._convert_value(item, item_hint) for item, item_hint in zip(value, args)
        )

    def _convert_typed_dict(
        self, value: dict[Any, Any], type_hint: Any
    ) -> dict[Any, Any]:
        field_hints, required_keys = _typed_dict_info(type_hint)
        missing_keys = required_keys - value.keys()
        if missing_keys:
            raise TypeError(
                f"Missing required keys {sorted(missing_keys)} for {type_hint}"
            )

        result: dict[Any, Any] = {}
        for key, item in value.items():
            field_hint = field_hints.get(key)
            if field_hint is None:
                continue
            if (
                item is None
                and key not in required_keys
                and not _allows_none(field_hint)
            ):
                continue
            result[key] = self._convert_value(item, field_hint)
        return result

    def _convert_dataclass(self, value: dict[Any, Any], type_hint: Any) -> Any:
        field_hints, field_names = _dataclass_info(type_hint)
        converted = {
            key: self._convert_value(item, field_hints[key])
            for key, item in value.items()
            if key in field_names
        }
        return type_hint(**converted)

    @staticmethod
    def _get_default(type_hint: Type | None) -> Any:
        if type_hint in (int, float):
            return 0
        if type_hint is bool:
            return False
        return None

    def to_data(self, values: List[Any]) -> Payload:
        result = bytearray()
        for index, value in enumerate(values):
            self._encoder.encode_into(value, result, -1)
            if index < len(values) - 1:
                result += _SPACE

        return Payload(data=bytes(result))
