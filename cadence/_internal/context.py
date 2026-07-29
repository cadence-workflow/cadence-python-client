"""Internal helpers for converting and propagating Cadence headers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from typing import Protocol

from cadence.api.v1.common_pb2 import Header, Payload
from cadence.context import ContextPropagator


class _HeaderCarrier(Protocol):
    """Proto message that carries a Cadence ``Header`` field."""

    header: Header


def header_to_dict(header: Header | None) -> dict[str, bytes]:
    """Return a detached copy of a proto header's byte payloads."""
    if header is None:
        return {}
    return {key: bytes(payload.data) for key, payload in header.fields.items()}


def header_from_dict(headers: Mapping[str, bytes]) -> Header | None:
    """Build a Header, omitting it entirely when no values were injected."""
    if not headers:
        return None
    return Header(fields={key: Payload(data=value) for key, value in headers.items()})


def inject_headers(propagators: Sequence[ContextPropagator]) -> dict[str, bytes]:
    """Inject ordered propagators, with later propagators winning duplicate keys."""
    headers: dict[str, bytes] = {}
    for propagator in propagators:
        headers.update(propagator.inject())
    return headers


def set_header(attrs: _HeaderCarrier, propagators: Sequence[ContextPropagator]) -> None:
    """Attach injected context to ``attrs``, leaving the field unset when empty."""
    header = header_from_dict(inject_headers(propagators))
    if header is not None:
        attrs.header.CopyFrom(header)


@contextmanager
def extract_headers(
    propagators: Sequence[ContextPropagator], headers: Mapping[str, bytes]
) -> Iterator[None]:
    """Activate propagators in order and reliably unwind partial extraction."""
    with ExitStack() as stack:
        for propagator in propagators:
            stack.enter_context(propagator.extract(headers))
        yield
