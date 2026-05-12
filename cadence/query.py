"""
Query definition for Cadence workflows.

This module provides the QueryDefinition class used internally by WorkflowDefinition
to track query handler metadata. Query handlers allow external callers to read
workflow state without affecting execution.
"""

import logging
from functools import update_wrapper
from typing import (
    Any,
    Callable,
    Generic,
    ParamSpec,
    TypeVar,
    TypedDict,
)

from cadence._internal.fn_signature import FnSignature
from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DataConverter

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class QueryDefinitionOptions(TypedDict, total=False):
    """Options for defining a query."""

    name: str


class QueryDefinition(Generic[P, T]):
    """
    Definition of a query handler with metadata.

    Similar to SignalDefinition but for query handlers.
    Query handlers must return a value (non-None return type).
    """

    def __init__(
        self,
        wrapped: Callable[P, T],
        name: str,
        signature: FnSignature,
    ) -> None:
        self._wrapped = wrapped
        self._name = name
        self._signature = signature
        update_wrapper(self, wrapped)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Call the wrapped query handler function."""
        return self._wrapped(*args, **kwargs)

    @property
    def name(self) -> str:
        """Get the query name."""
        return self._name

    @property
    def wrapped(self) -> Callable[P, T]:
        """Get the wrapped query handler function."""
        return self._wrapped

    def params_from_payload(
        self, data_converter: DataConverter, payload: Payload
    ) -> list[Any]:
        return self._signature.params_from_payload(data_converter, payload)

    @property
    def return_type(self) -> type:
        return self._signature.return_type

    @staticmethod
    def wrap(
        fn: Callable[P, T], opts: QueryDefinitionOptions
    ) -> "QueryDefinition[P, T]":
        """
        Wrap a function as a QueryDefinition.

        Args:
            fn: The query handler function to wrap
            opts: Options for the query definition

        Returns:
            A QueryDefinition instance

        Raises:
            ValueError: If return type is None (queries must return a value)
        """
        name = opts.get("name") or fn.__qualname__
        sig = FnSignature.of(fn)
        rt = sig.return_type
        if rt in (None, type(None)):
            raise ValueError(
                f"Query handler '{fn.__qualname__}' must have a non-None return type "
                f"(queries must return values). Use a type annotation like -> str, -> int, etc."
            )
        return QueryDefinition(fn, name, sig)
