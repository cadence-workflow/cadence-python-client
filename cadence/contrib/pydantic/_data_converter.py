"""msgspec data converter with Pydantic ``BaseModel`` encode/decode hooks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from cadence.data_converter import DefaultDataConverter


def _enc_hook(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    raise TypeError(f"Encoding objects of type {type(obj).__name__} is unsupported")


def _dec_hook(typ: Any, obj: Any) -> Any:
    if isinstance(typ, type) and issubclass(typ, BaseModel):
        return typ.model_validate(obj)
    raise TypeError(f"Decoding objects of type {typ} is unsupported")


class PydanticDataConverter(DefaultDataConverter):
    """:class:`~cadence.data_converter.DefaultDataConverter` plus Pydantic models.

    Uses msgspec ``enc_hook`` / ``dec_hook`` so ``pydantic.BaseModel`` values
    are dumped and validated while every other type stays on the default
    msgspec path.
    """

    def __init__(self) -> None:
        super().__init__(enc_hook=_enc_hook, dec_hook=_dec_hook)
