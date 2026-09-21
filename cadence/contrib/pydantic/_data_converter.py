"""msgspec JSON converter with Pydantic validation for typed payloads."""

from __future__ import annotations

from types import UnionType
from typing import (
    Annotated,
    Any,
    Literal,
    NotRequired,
    Required,
    Sequence,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from msgspec import json
from pydantic import BaseModel, TypeAdapter, ValidationError
from typing_extensions import is_typeddict

from cadence.data_converter import DefaultDataConverter


def _enc_hook(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    raise TypeError(f"Encoding objects of type {type(obj).__name__} is unsupported")


def _dec_hook(typ: Any, obj: Any) -> Any:
    if isinstance(typ, type) and issubclass(typ, BaseModel):
        return typ.model_validate(obj)
    raise TypeError(f"Decoding objects of type {typ} is unsupported")


def _unwrap_field_hint(type_hint: Any) -> Any:
    if get_origin(type_hint) in (Required, NotRequired):
        return get_args(type_hint)[0]
    return type_hint


def _matches_typed_dict_tag(value: dict[Any, Any], type_hint: Any) -> bool:
    field_hint = get_type_hints(type_hint, include_extras=True).get("type")
    if field_hint is None:
        return False
    field_hint = _unwrap_field_hint(field_hint)
    return get_origin(field_hint) is Literal and value.get("type") in get_args(
        field_hint
    )


def _canonicalize_optional_typed_dict_nones(value: Any, type_hint: Any) -> Any:
    origin = get_origin(type_hint)
    if origin is Annotated:
        return _canonicalize_optional_typed_dict_nones(value, get_args(type_hint)[0])
    if origin in (Union, UnionType):
        args = get_args(type_hint)
        if isinstance(value, list):
            list_hints = [arg for arg in args if get_origin(arg) is list]
            if len(list_hints) == 1:
                return _canonicalize_optional_typed_dict_nones(value, list_hints[0])
        if isinstance(value, dict):
            typed_dict_hints = [
                arg
                for arg in args
                if is_typeddict(arg) and _matches_typed_dict_tag(value, arg)
            ]
            if len(typed_dict_hints) == 1:
                return _canonicalize_optional_typed_dict_nones(
                    value, typed_dict_hints[0]
                )
        return value
    if origin is list and isinstance(value, list):
        item_hint = get_args(type_hint)[0]
        return [
            _canonicalize_optional_typed_dict_nones(item, item_hint) for item in value
        ]
    if is_typeddict(type_hint) and isinstance(value, dict):
        field_hints = get_type_hints(type_hint, include_extras=True)
        result: dict[Any, Any] = {}
        for key, item in value.items():
            field_hint = field_hints.get(key)
            if field_hint is None:
                result[key] = item
                continue
            field_origin = get_origin(field_hint)
            is_optional_key = field_origin is NotRequired or (
                field_origin is not Required and key not in type_hint.__required_keys__
            )
            if item is None and is_optional_key:
                continue
            result[key] = _canonicalize_optional_typed_dict_nones(
                item, _unwrap_field_hint(field_hint)
            )
        return result
    return value


class PydanticDataConverter(DefaultDataConverter):
    """:class:`~cadence.data_converter.DefaultDataConverter` plus Pydantic models.

    Uses msgspec for JSON encoding and its supported decoding paths. When
    msgspec cannot represent a concrete type hint, Pydantic ``TypeAdapter``
    validates it instead. This includes unions with multiple ``TypedDict``
    members and unions containing Pydantic-supported custom types. Optional
    ``TypedDict`` keys represented as ``None`` may be validated as omitted
    while the original wire value is preserved.
    """

    def __init__(self) -> None:
        super().__init__(enc_hook=_enc_hook, dec_hook=_dec_hook)
        self._type_adapters: dict[Any, TypeAdapter[Any]] = {}
        self._msgspec_type_hints: set[Any] = set()

    def _convert_into(
        self, values: list[Any], type_hints: Sequence[Type | None]
    ) -> list[Any]:
        results: list[Any] = []
        for index, type_hint in enumerate(type_hints):
            if index >= len(values):
                results.append(self._get_default(type_hint))
            elif type_hint and type_hint is not Any:
                adapter = self._type_adapters.get(type_hint)
                if adapter is None and type_hint not in self._msgspec_type_hints:
                    try:
                        json.Decoder(type=type_hint, dec_hook=_dec_hook)
                    except TypeError:
                        adapter = TypeAdapter(type_hint)
                        self._type_adapters[type_hint] = adapter
                    else:
                        self._msgspec_type_hints.add(type_hint)
                if adapter is None:
                    converted = super()._convert_into(
                        values[index : index + 1], [type_hint]
                    )[0]
                else:
                    try:
                        converted = adapter.validate_python(values[index])
                    except ValidationError:
                        canonical_value = _canonicalize_optional_typed_dict_nones(
                            values[index], type_hint
                        )
                        if canonical_value == values[index]:
                            raise
                        adapter.validate_python(canonical_value)
                        converted = values[index]
                results.append(converted)
            else:
                results.append(values[index])
        return results
