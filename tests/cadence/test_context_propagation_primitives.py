from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast

import pytest

from cadence._internal.context_propagation import (
    context_header_from_propagators,
    context_propagation_scope,
    header_to_context_fields,
    normalize_context_propagators,
)
from cadence.api.v1.common_pb2 import Header
from cadence.context import ContextPropagationError


class _ContextVarPropagator:
    def __init__(self, key: str = "x-request-id") -> None:
        self._key = key
        self.value: ContextVar[str | None] = ContextVar(key, default=None)

    def inject(self) -> dict[str, bytes]:
        value = self.value.get()
        return {} if value is None else {self._key: value.encode()}

    @contextmanager
    def extract(self, headers: Mapping[str, bytes]) -> Iterator[None]:
        raw_value = headers.get(self._key)
        token = self.value.set(raw_value.decode() if raw_value is not None else None)
        try:
            yield
        finally:
            self.value.reset(token)


class _StaticPropagator:
    def __init__(self, fields: Mapping[str, bytes]) -> None:
        self._fields = fields

    def inject(self) -> Mapping[str, bytes]:
        return self._fields

    @contextmanager
    def extract(self, _headers: Mapping[str, bytes]) -> Iterator[None]:
        yield


class _BrokenPropagator:
    def inject(self) -> Mapping[str, bytes]:
        raise ValueError("cannot inject")

    @contextmanager
    def extract(self, headers: Mapping[str, bytes]) -> Iterator[None]:
        if headers:
            yield
            return
        raise ValueError("cannot extract")


class _RecordingPropagator(_StaticPropagator):
    def __init__(self, events: list[str], name: str) -> None:
        super().__init__({})
        self._events = events
        self._name = name

    @contextmanager
    def extract(self, _headers: Mapping[str, bytes]) -> Iterator[None]:
        self._events.append(f"enter:{self._name}")
        try:
            yield
        finally:
            self._events.append(f"exit:{self._name}")


class _CleanupBrokenPropagator(_StaticPropagator):
    @contextmanager
    def extract(self, _headers: Mapping[str, bytes]) -> Iterator[None]:
        try:
            yield
        finally:
            raise ValueError("cannot clean up")


def test_header_codec_preserves_raw_bytes_and_contextvar_scope() -> None:
    propagator = _ContextVarPropagator()
    header = Header()
    header.fields["go.trace"].data = b"\x00\xffgo"
    header.fields["x-request-id"].data = b"request-1"
    header.fields["java.trace"].data = b"\x80java\x00"

    assert header_to_context_fields(header) == {
        "go.trace": b"\x00\xffgo",
        "x-request-id": b"request-1",
        "java.trace": b"\x80java\x00",
    }
    with context_propagation_scope((propagator,), header):
        assert propagator.value.get() == "request-1"
    assert propagator.value.get() is None


def test_injection_rejects_collisions_and_invalid_values() -> None:
    with pytest.raises(ContextPropagationError, match="Multiple context propagators"):
        context_header_from_propagators(
            (_StaticPropagator({"shared": b"one"}), _StaticPropagator({"shared": b"two"}))
        )

    invalid = _StaticPropagator(cast(Mapping[str, bytes], {"invalid": "value"}))
    with pytest.raises(ContextPropagationError, match="non-bytes"):
        context_header_from_propagators((invalid,))

    with pytest.raises(ContextPropagationError, match="inject failed"):
        context_header_from_propagators((_BrokenPropagator(),))


def test_scope_reverses_cleanup_and_wraps_propagator_errors() -> None:
    events: list[str] = []
    with context_propagation_scope(
        (_RecordingPropagator(events, "first"), _RecordingPropagator(events, "second")),
        {},
    ):
        assert events == ["enter:first", "enter:second"]
    assert events == ["enter:first", "enter:second", "exit:second", "exit:first"]

    with pytest.raises(ContextPropagationError, match="extract failed"):
        with context_propagation_scope((_BrokenPropagator(),), {}):
            pass
    with pytest.raises(ContextPropagationError, match="cleanup failed"):
        with context_propagation_scope((_CleanupBrokenPropagator({}),), {}):
            pass


def test_normalization_snapshots_configured_propagators() -> None:
    propagator = _StaticPropagator({})
    configured = [propagator]

    normalized = normalize_context_propagators(configured)
    configured.clear()

    assert normalized == (propagator,)
    assert normalize_context_propagators(None) == ()
