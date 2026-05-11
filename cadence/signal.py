"""
Signal definition for Cadence workflows.

This module provides the SignalDefinition class used internally by WorkflowDefinition
to track signal handler metadata.
"""

import logging
from functools import update_wrapper
from inspect import Signature
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


class SignalDefinitionOptions(TypedDict, total=False):
    """Options for defining a signal."""

    name: str


class SignalDefinition(Generic[P, T]):
    """
    Definition of a signal handler with metadata.

    Similar to ActivityDefinition but for signal handlers.
    Provides type safety and metadata for signal handlers.
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
        """Call the wrapped signal handler function."""
        return self._wrapped(*args, **kwargs)

    @property
    def name(self) -> str:
        """Get the signal name."""
        return self._name

    @property
    def wrapped(self) -> Callable[P, T]:
        """Get the wrapped signal handler function."""
        return self._wrapped

    def params_from_payload(
        self, data_converter: DataConverter, payload: Payload
    ) -> list[Any]:
        return self._signature.params_from_payload(data_converter, payload)

    @staticmethod
    def wrap(
        fn: Callable[P, T], opts: SignalDefinitionOptions
    ) -> "SignalDefinition[P, T]":
        """
        Wrap a function as a SignalDefinition.

        This is an internal method used by WorkflowDefinition to create signal definitions
        from methods decorated with @workflow.signal.

        Args:
            fn: The signal handler function to wrap
            opts: Options for the signal definition

        Returns:
            A SignalDefinition instance

        Raises:
            ValueError: If return type is not None
        """
        name = opts.get("name") or fn.__qualname__
        sig = FnSignature.of(fn)
        rt = sig.return_type
        if rt not in (None, type(None), Signature.empty, Any):
            raise ValueError(
                f"Signal handler '{fn.__qualname__}' must return None "
                f"(signals cannot return values), got {rt}"
            )
        return SignalDefinition(fn, name, sig)
