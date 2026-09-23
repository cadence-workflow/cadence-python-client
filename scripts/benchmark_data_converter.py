"""Decode/encode benchmarks for :class:`DefaultDataConverter`.

Compares the current converter against two baselines on shared paths:

- ``baseline``: the pre-fix implementation (stdlib JSON parse + a single
  ``msgspec.convert`` per type hint). Represents the msgspec fast path.
- ``naive-union``: baseline plus per-variant retries when msgspec raises
  ``TypeError`` on unions of dict-like types.

Paths that only the current converter supports (explicit-null
canonicalization on optional TypedDict keys, unions nested in containers)
report absolute numbers with no ratio.

Run from the repo root:

    uv run --all-extras python scripts/benchmark_data_converter.py
"""

import dataclasses
import sys
import time
from json import JSONDecoder
from typing import (
    Any,
    List,
    NotRequired,
    Optional,
    Sequence,
    Type,
    TypedDict,
    Union,
    cast,
)

from msgspec import ValidationError, convert, json
from types import UnionType
from typing import get_args, get_origin

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DefaultDataConverter

try:
    from agents import TResponseInputItem

    _OPENAI_INPUT_TYPE: Any = cast(Type, str | list[TResponseInputItem])
except ModuleNotFoundError:
    _OPENAI_INPUT_TYPE = None


@dataclasses.dataclass
class _DataClassItem:
    foo: str
    bar: int


class _NullableItem(TypedDict):
    name: str
    note: NotRequired[str]
    tag: NotRequired[Optional[str]]


class _ItemDict(TypedDict):
    name: str
    count: int


class _BaselineConverter:
    """Pre-fix decode path: one ``msgspec.convert`` per type hint."""

    def __init__(self) -> None:
        self._decoder = JSONDecoder(strict=False)
        self._encoder = json.Encoder()

    def from_data(self, payload: Payload, type_hints: Sequence[Any]) -> List[Any]:
        results: List[Any] = []
        start, end = 0, len(payload.data)
        data = payload.data.decode()
        while start < end and len(results) < len(type_hints):
            value, value_end = self._decoder.raw_decode(data[start:end])
            start += value_end + 1
            results.append(value)
        converted: List[Any] = []
        for i, type_hint in enumerate(type_hints):
            value = results[i] if i < len(results) else None
            if i < len(results) and type_hint and type_hint is not Any:
                value = self._convert(value, type_hint)
            converted.append(value)
        return converted

    def _convert(self, value: Any, type_hint: Any) -> Any:
        return convert(value, type_hint, dec_hook=None)

    def to_data(self, values: List[Any]) -> Payload:
        result = bytearray()
        for index, value in enumerate(values):
            self._encoder.encode_into(value, result, -1)
            if index < len(values) - 1:
                result += b" "
        return Payload(data=bytes(result))


class _NaiveUnionConverter(_BaselineConverter):
    """Baseline plus per-variant retries on ``TypeError`` (PR #179 shape)."""

    def _convert(self, value: Any, type_hint: Any) -> Any:
        try:
            return convert(value, type_hint, dec_hook=None)
        except TypeError:
            if get_origin(type_hint) not in (Union, UnionType):
                raise
        for variant in get_args(type_hint):
            if variant is type(None):
                continue
            try:
                return self._convert(value, variant)
            except (TypeError, ValidationError):
                continue
        raise TypeError(f"Unable to convert value into any variant of {type_hint}")


def _bench(fn: Any, iterations: int) -> float:
    fn()  # warm up
    start = time.perf_counter_ns()
    for _ in range(iterations):
        fn()
    return (time.perf_counter_ns() - start) / iterations


def _run_case(
    name: str,
    json_data: bytes,
    type_hint: Any,
    iterations: int,
    converters: dict[str, Any],
) -> None:
    payload = Payload(data=json_data)
    timings: dict[str, float] = {}
    for label, converter in converters.items():
        decode = lambda: converter.from_data(payload, [type_hint])  # noqa: E731
        try:
            decode()
        except Exception:
            print(f"  {label:<12} unsupported")
            continue
        timings[label] = _bench(decode, iterations)

    current = timings.get("current")
    assert current is not None, "current converter must support every case"
    for label, ns in timings.items():
        if label == "current":
            continue
        print(f"  {label:<12} {ns / 1000:>10.1f} us   current is {ns / current:>5.2f}x")
    print(f"  {'current':<12} {current / 1000:>10.1f} us")


def main() -> None:
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    converters: dict[str, Any] = {
        "current": DefaultDataConverter(),
        "baseline": _BaselineConverter(),
        "naive-union": _NaiveUnionConverter(),
    }

    cases = [
        ("scalar str", b'"hello world"', str),
        ("scalar int", b"42", int),
        ("dataclass", b'{"foo": "hello", "bar": 42}', _DataClassItem),
        (
            "typed dict clean",
            b'{"name": "widget", "note": "x", "tag": "y"}',
            _NullableItem,
        ),
        (
            "typed dict canonicalize",
            b'{"name": "widget", "note": null, "tag": null}',
            _NullableItem,
        ),
        (
            "union dataclass|dict",
            b'{"name": "widget", "count": 3}',
            Union[_DataClassItem, _ItemDict],
        ),
        (
            "union in list",
            b'[{"foo": "a", "bar": 1}, {"name": "w", "count": 3}]',
            list[Union[_DataClassItem, _ItemDict]],
        ),
        (
            "list[dataclass] x50",
            b"[" + b",".join([b'{"foo": "a", "bar": 1}'] * 50) + b"]",
            list[_DataClassItem],
        ),
    ]
    if _OPENAI_INPUT_TYPE is not None:
        cases.append(
            (
                "openai union",
                b'[{"role": "user", "content": "Hello"},'
                b'{"type": "function_call_output", "call_id": "c1", "output": "Hi"}]',
                _OPENAI_INPUT_TYPE,
            )
        )

    for name, data, hint in cases:
        print(f"\n{name}  ({iterations} iterations)")
        _run_case(name, data, hint, iterations, converters)

    print("\nencode dataclass")
    value = _DataClassItem(foo="hello", bar=42)
    for label, converter in converters.items():
        ns = _bench(lambda: converter.to_data([value]), iterations)
        print(f"  {label:<12} {ns / 1000:>10.1f} us")


if __name__ == "__main__":
    main()
