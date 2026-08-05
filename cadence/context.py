"""Context propagation between Cadence clients, workflows, and activities."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import ContextManager, Generic, Protocol, TypeVar, cast

T = TypeVar("T")
_UNSET = object()


class ContextPropagator(Protocol):
    """Inject and extract application context in Cadence headers."""

    @abstractmethod
    def inject(self) -> Mapping[str, bytes]:
        """Return headers for the context currently active in this execution."""
        raise NotImplementedError()

    @abstractmethod
    def extract(self, headers: Mapping[str, bytes]) -> ContextManager[None]:
        """Activate context from ``headers`` for the duration of a scope."""
        raise NotImplementedError()


class ContextVarPropagator(ContextPropagator, Generic[T]):
    """A generic :class:`ContextVar`-backed context propagator."""

    def __init__(
        self,
        var: ContextVar[T],
        header_key: str,
        serialize: Callable[[T], bytes],
        deserialize: Callable[[bytes], T],
    ) -> None:
        self._var = var
        self._header_key = header_key
        self._serialize = serialize
        self._deserialize = deserialize

    def inject(self) -> Mapping[str, bytes]:
        value = self._var.get(_UNSET)
        if value is _UNSET:
            return {}
        return {self._header_key: self._serialize(cast(T, value))}

    @contextmanager
    def extract(self, headers: Mapping[str, bytes]) -> Iterator[None]:
        if self._header_key not in headers:
            yield
            return
        token = self._var.set(self._deserialize(headers[self._header_key]))
        try:
            yield
        finally:
            self._var.reset(token)
