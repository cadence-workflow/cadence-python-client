"""Internal helpers for converting and propagating Cadence headers."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from typing import Protocol

from cadence.api.v1.common_pb2 import Header, Payload
from cadence.context import ContextPropagator

logger = logging.getLogger(__name__)


class _HeaderCarrier(Protocol):
    """Proto message that carries a Cadence ``Header`` field."""

    header: Header


def header_to_dict(header: Header) -> dict[str, bytes]:
    """Return a detached copy of a proto header's byte payloads."""
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
        try:
            headers.update(propagator.inject())
        except Exception:
            logger.exception("Context propagator inject failed; skipping propagator")
    return headers


def set_header(attrs: _HeaderCarrier, propagators: Sequence[ContextPropagator]) -> None:
    """Attach injected context to ``attrs``, leaving the field unset when empty."""
    set_header_from_dict(attrs, inject_headers(propagators))


def set_header_from_dict(attrs: _HeaderCarrier, headers: Mapping[str, bytes]) -> None:
    """Attach ``headers`` to ``attrs``, leaving the field unset when empty."""
    header = header_from_dict(headers)
    if header is not None:
        attrs.header.CopyFrom(header)


def validate_propagators(propagators: Sequence[ContextPropagator]) -> None:
    """Fail fast when a propagator does not implement the protocol."""
    for index, propagator in enumerate(propagators):
        if not callable(getattr(propagator, "inject", None)):
            raise TypeError(
                f"context_propagators[{index}] is missing a callable inject() method"
            )
        if not callable(getattr(propagator, "extract", None)):
            raise TypeError(
                f"context_propagators[{index}] is missing a callable extract() method"
            )


@contextmanager
def extract_headers(
    propagators: Sequence[ContextPropagator], headers: Mapping[str, bytes]
) -> Iterator[None]:
    """Activate propagators in order and reliably unwind partial extraction."""
    with ExitStack() as stack:
        for propagator in propagators:
            try:
                stack.enter_context(propagator.extract(headers))
            except Exception:
                logger.exception(
                    "Context propagator extract failed; skipping propagator"
                )
        yield
