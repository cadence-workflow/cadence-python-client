"""Shared Cadence header codecs and context-propagation scopes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager

from cadence.api.v1.common_pb2 import Header
from cadence.context import ContextPropagator
from cadence.error import ContextPropagationError


def normalize_context_propagators(
    propagators: Sequence[ContextPropagator] | None,
) -> tuple[ContextPropagator, ...]:
    """Snapshot propagators so runtime behavior cannot change after setup."""
    return tuple(propagators or ())


def header_to_context_fields(header: Header | None) -> dict[str, bytes]:
    """Convert a Cadence Header to the cross-SDK ``str -> bytes`` carrier."""
    if header is None:
        return {}
    return {key: bytes(payload.data) for key, payload in header.fields.items()}


def inject_context_fields(
    propagators: Sequence[ContextPropagator],
) -> dict[str, bytes]:
    """Collect and validate fields emitted by configured propagators."""
    fields: dict[str, bytes] = {}
    for propagator in propagators:
        try:
            emitted = propagator.inject()
        except Exception as exc:
            raise ContextPropagationError(
                f"Context propagation inject failed for {type(propagator).__name__}"
            ) from exc
        if not isinstance(emitted, Mapping):
            raise ContextPropagationError(
                f"{type(propagator).__name__}.inject() must return a mapping"
            )
        for key, value in emitted.items():
            if not isinstance(key, str):
                raise ContextPropagationError(
                    f"{type(propagator).__name__}.inject() emitted a non-string key"
                )
            if not isinstance(value, (bytes, bytearray, memoryview)):
                raise ContextPropagationError(
                    f"{type(propagator).__name__}.inject() emitted a non-bytes value "
                    f"for header {key!r}"
                )
            if key in fields:
                raise ContextPropagationError(
                    f"Multiple context propagators emitted header {key!r}"
                )
            fields[key] = bytes(value)
    return fields


def context_header_from_propagators(
    propagators: Sequence[ContextPropagator],
) -> Header | None:
    """Build an independent protobuf Header for outbound propagation."""
    fields = inject_context_fields(propagators)
    if not fields:
        return None
    header = Header()
    for key, value in fields.items():
        header.fields[key].data = value
    return header


@contextmanager
def context_propagation_scope(
    propagators: Sequence[ContextPropagator],
    header_or_fields: Header | Mapping[str, bytes] | None,
) -> Iterator[None]:
    """Install incoming context for one logical workflow or activity invocation."""
    fields: Mapping[str, bytes]
    if isinstance(header_or_fields, Header):
        fields = header_to_context_fields(header_or_fields)
    elif header_or_fields is None:
        fields = {}
    else:
        fields = header_or_fields

    stack = ExitStack()
    try:
        for propagator in propagators:
            try:
                scope = propagator.extract(fields)
                stack.enter_context(scope)
            except ContextPropagationError:
                raise
            except Exception as exc:
                raise ContextPropagationError(
                    f"Context propagation extract failed for {type(propagator).__name__}"
                ) from exc
    except Exception:
        try:
            stack.close()
        except Exception as cleanup_error:
            raise ContextPropagationError(
                "Context propagation cleanup failed after extract error"
            ) from cleanup_error
        raise

    try:
        yield
    finally:
        try:
            stack.close()
        except Exception as exc:
            raise ContextPropagationError("Context propagation cleanup failed") from exc
