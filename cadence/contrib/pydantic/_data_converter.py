"""Pydantic v2 data converter for Cadence payloads.

Mirrors Temporal's ``PydanticJSONPlainPayloadConverter``: payloads are
encoded with ``pydantic_core.to_json`` and decoded through cached
``pydantic.TypeAdapter`` instances. In addition to ``BaseModel`` this
covers every type Pydantic supports, including ``TypedDict``, dataclasses,
and unions of dict-like types, which msgspec cannot schema-compile
(https://github.com/msgspec/msgspec/issues/982).

One Cadence-specific addition on top of the Temporal design: some
producers emit an explicit ``null`` for keys a ``TypedDict`` declares
``NotRequired`` but non-nullable (e.g. the OpenAI Agents SDK emits
``"id": null`` on response items). Pydantic rejects those payloads, so a
failed payload whose type hint contains a ``TypedDict`` is retried after
dropping exactly those nulls. Every other validation error propagates
unchanged.
"""

from __future__ import annotations

import dataclasses
from functools import lru_cache
from types import UnionType
from typing import (
    Annotated,
    Any,
    List,
    NotRequired,
    Required,
    Sequence,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import TypeAdapter
from pydantic_core import PydanticSerializationError, ValidationError, to_json
from typing_extensions import is_typeddict

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import _SPACE, DefaultDataConverter

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
    if id(type_hint) in seen:  # pragma: no cover - guards recursive hints
        return False
    seen = seen | {id(type_hint)}
    if isinstance(type_hint, type) and dataclasses.is_dataclass(type_hint):
        return any(
            _contains_typed_dict(hint, seen)
            for hint in _dataclass_fields(type_hint).values()
        )
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
def _typed_dict_info(type_hint: Any) -> tuple[dict[str, Any], frozenset[str]]:
    field_hints = get_type_hints(type_hint, include_extras=True)
    required_keys = set(type_hint.__required_keys__)
    for key, field_hint in field_hints.items():
        origin = get_origin(field_hint)
        if origin is Required:
            required_keys.add(key)
        elif origin is NotRequired:
            required_keys.discard(key)
    return field_hints, frozenset(required_keys)


@lru_cache(maxsize=1024)
def _dataclass_fields(type_hint: Any) -> dict[str, Any]:
    return get_type_hints(type_hint, include_extras=True)


def _canonicalize_nulls(value: Any, type_hint: Any) -> Any:
    """Drop explicit nulls on keys declared NotRequired but non-nullable.

    Recurses through unions and containers so nested ``TypedDict`` values
    are cleaned too. A dict matched against a union is cleaned against the
    variant that declares every key present in the payload.
    """
    hint = _unwrap(type_hint)
    origin = get_origin(hint)
    args = get_args(hint)

    if is_typeddict(hint):
        if not isinstance(value, dict):
            return value
        field_hints, required_keys = _typed_dict_info(hint)
        result = {}
        for key, item in value.items():
            field_hint = field_hints.get(key)
            if field_hint is None:
                result[key] = item
            elif (
                item is None
                and key not in required_keys
                and not _allows_none(field_hint)
            ):
                continue
            else:
                result[key] = _canonicalize_nulls(item, field_hint)
        return result

    if origin in (Union, UnionType):
        variants = [v for v in (_unwrap(a) for a in args) if v is not type(None)]
        if isinstance(value, dict):
            # Variants disagree on nullability for the same key, so a single
            # merged rule cannot satisfy all of them. Canonicalize against
            # the variant that declares every present key: a discriminated
            # union member matches at most one variant's shape. A dict[...]
            # variant covers any keys; a dict-like variant that does not
            # cover them is the last resort.
            first_field_variant: Any = None
            first_dict_variant: Any = None
            for variant in variants:
                variant_fields: dict[str, Any] | None = None
                if get_origin(variant) is dict:
                    if first_dict_variant is None:
                        first_dict_variant = variant
                elif is_typeddict(variant):
                    variant_fields, _ = _typed_dict_info(variant)
                elif isinstance(variant, type) and dataclasses.is_dataclass(variant):
                    variant_fields = _dataclass_fields(variant)
                if variant_fields is None:
                    continue
                if first_field_variant is None:
                    first_field_variant = variant
                if set(value) <= set(variant_fields):
                    return _canonicalize_nulls(value, variant)
            for fallback in (first_dict_variant, first_field_variant):
                if fallback is not None:
                    return _canonicalize_nulls(value, fallback)
            return value
        if isinstance(value, (list, tuple)):
            # Merge the item hints of every list/set/tuple variant the value
            # could match, then canonicalize each element against the union
            # of them. Fixed-length tuple variants cannot be merged per
            # position and are left alone.
            item_hints: list[Any] = []
            for variant in variants:
                variant_args = get_args(variant)
                variant_origin = get_origin(variant)
                if (variant_origin in (list, set, frozenset) and variant_args) or (
                    variant_origin is tuple
                    and len(variant_args) == 2
                    and variant_args[1] is Ellipsis
                ):
                    item_hints.append(variant_args[0])
            if not item_hints:
                return value
            item_hint = (
                Union[tuple(item_hints)] if len(item_hints) > 1 else item_hints[0]
            )
            return [_canonicalize_nulls(item, item_hint) for item in value]
        return value

    if origin is list and isinstance(value, list):
        item_hint = args[0] if args else Any
        return [_canonicalize_nulls(item, item_hint) for item in value]

    if origin is tuple and isinstance(value, (list, tuple)):
        if len(args) == 2 and args[1] is Ellipsis:
            return [_canonicalize_nulls(item, args[0]) for item in value]
        if len(value) == len(args):
            return [
                _canonicalize_nulls(item, item_hint)
                for item, item_hint in zip(value, args)
            ]
        return list(value)

    if origin is dict and isinstance(value, dict):
        value_hint = args[1] if len(args) == 2 else Any
        return {
            key: _canonicalize_nulls(item, value_hint) for key, item in value.items()
        }

    if (
        isinstance(hint, type)
        and dataclasses.is_dataclass(hint)
        and isinstance(value, dict)
    ):
        field_hints = _dataclass_fields(hint)
        return {
            key: (
                _canonicalize_nulls(item, field_hints[key])
                if key in field_hints
                else item
            )
            for key, item in value.items()
        }

    return value


def _canonicalize_candidates(value: Any, type_hint: Any) -> list[Any]:
    """Canonicalize ``value`` against each union variant separately.

    A null that one variant allows and another rejects must be dropped for
    the second variant but kept for the first, so a union produces one
    candidate per variant, in declared order.
    """
    hint = _unwrap(type_hint)
    if get_origin(hint) in (Union, UnionType):
        variants = [a for a in get_args(hint) if _unwrap(a) is not type(None)]
        return [_canonicalize_nulls(value, variant) for variant in variants]
    return [_canonicalize_nulls(value, hint)]


class PydanticDataConverter(DefaultDataConverter):
    """Data converter backed by Pydantic instead of msgspec.

    Encodes with ``pydantic_core.to_json`` and decodes through a cached
    :class:`pydantic.TypeAdapter` per type hint, mirroring Temporal's
    ``PydanticJSONPlainPayloadConverter``. Supports every type Pydantic
    supports: ``BaseModel``, ``TypedDict``, dataclasses, unions of
    dict-like types, datetimes, UUIDs, enums, and plain JSON types.

    Use this converter when activity signatures rely on Pydantic models or
    on type hints msgspec cannot compile, such as unions of ``TypedDict`` types
    (the OpenAI Agents SDK ``str | list[TResponseInputItem]`` annotation).
    """

    def __init__(self, *, max_cached_type_adapters: int | None = 1024) -> None:
        """Create the converter.

        Args:
            max_cached_type_adapters: Maximum number of ``TypeAdapter``
                instances to cache, with least-recently-used eviction.
                Defaults to 1024. If ``None``, the cache is unbounded. If
                zero, caching is disabled.
        """
        super().__init__()
        if max_cached_type_adapters is not None and max_cached_type_adapters < 0:
            raise ValueError("max_cached_type_adapters cannot be negative")
        self._type_adapter = lru_cache(maxsize=max_cached_type_adapters)(TypeAdapter)

    def to_data(self, values: List[Any]) -> Payload:
        result = bytearray()
        for index, value in enumerate(values):
            try:
                result += to_json(value)
            except PydanticSerializationError as e:
                raise TypeError(
                    f"Encoding objects of type {type(value).__name__} is unsupported"
                ) from e
            if index < len(values) - 1:
                result += _SPACE
        return Payload(data=bytes(result))

    def _convert_into(
        self, values: List[Any], type_hints: Sequence[Type | None]
    ) -> List[Any]:
        # Same loop as DefaultDataConverter._convert_into, but conversion is
        # delegated to _convert_value so this converter does not need any
        # changes in the base class.
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
            adapter = self._type_adapter(type_hint)
        except TypeError:
            # Distinguish an unhashable hint (bypass the cache) from a
            # TypeError raised while constructing the adapter (re-raise).
            try:
                hash(type_hint)
            except TypeError:
                adapter = TypeAdapter(type_hint)
            else:  # pragma: no cover - TypeAdapter raises TypeError only on exotic hints
                raise
        try:
            return adapter.validate_python(value)
        except ValidationError:
            # The only failure canonicalization can repair is an explicit
            # null on a non-nullable NotRequired TypedDict key. Any other
            # validation error propagates immediately.
            if _contains_typed_dict(type_hint) and _contains_none(value):
                for candidate in _canonicalize_candidates(value, type_hint):
                    try:
                        return adapter.validate_python(candidate)
                    except ValidationError:
                        continue
            raise
