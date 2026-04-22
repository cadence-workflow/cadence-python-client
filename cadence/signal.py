"""
Signal definition for Cadence workflows.

This module provides the SignalDefinition class used internally by WorkflowDefinition
to track signal handler metadata.
"""

import inspect
import logging
from dataclasses import dataclass
from functools import update_wrapper
from inspect import Parameter, signature
from json import JSONDecoder
from typing import (
    Callable,
    Generic,
    ParamSpec,
    Type,
    TypeVar,
    TypedDict,
    get_type_hints,
    Any,
)

from cadence.api.v1.common_pb2 import Payload

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


@dataclass(frozen=True)
class SignalParameter:
    """Parameter metadata for a signal handler."""

    name: str
    type_hint: Type | None
    has_default: bool
    default_value: Any


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
        params: list[SignalParameter],
    ):
        self._wrapped = wrapped
        self._name = name
        self._params = params
        update_wrapper(self, wrapped)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Call the wrapped signal handler function."""
        return self._wrapped(*args, **kwargs)

    @property
    def name(self) -> str:
        """Get the signal name."""
        return self._name

    @property
    def params(self) -> list[SignalParameter]:
        """Get the signal parameters."""
        return self._params

    @property
    def wrapped(self) -> Callable[P, T]:
        """Get the wrapped signal handler function."""
        return self._wrapped

    def params_from_payload(self, data_converter: Any, payload: Payload) -> list[Any]:
        if not self._params:
            return []

        payload_count = _count_payload_values(payload)

        for i, param in enumerate(self._params):
            if i >= payload_count and not param.has_default:
                raise ValueError(
                    f"Signal '{self._name}': required parameter '{param.name}' "
                    f"(position {i}) not provided in payload "
                    f"({payload_count} value(s) present)"
                )

        # Only decode the values actually present in the payload (capped at
        # param count so extra trailing values are ignored).  This avoids
        # relying on the DataConverter returning a list whose length equals
        # len(type_hints) — a custom converter may return fewer elements.
        decode_count = min(payload_count, len(self._params))
        type_hints = [p.type_hint for p in self._params[:decode_count]]
        decoded: list[Any] = data_converter.from_data(payload, type_hints)

        # Append Python-defined defaults for params absent from the payload.
        for param in self._params[decode_count:]:
            if param.has_default:
                decoded.append(param.default_value)

        return decoded

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
        params = _get_signal_signature(fn)
        _validate_signal_return_type(fn)

        return SignalDefinition[P, T](fn, name, params)


def _validate_signal_return_type(fn: Callable) -> None:
    """
    Validate that signal handler returns None.

    Args:
        fn: The signal handler function

    Raises:
        ValueError: If return type is not None
    """
    try:
        hints = get_type_hints(fn)
        ret_type = hints.get("return", inspect.Signature.empty)

        # ``get_type_hints`` normalizes the ``None`` annotation to ``type(None)``
        # (a.k.a. ``NoneType``), so both must be treated as a valid return type.
        if (
            ret_type is not None
            and ret_type is not type(None)
            and ret_type is not inspect.Signature.empty
        ):
            raise ValueError(
                f"Signal handler '{fn.__qualname__}' must return None "
                f"(signals cannot return values), got {ret_type}"
            )
    except NameError:
        pass


def _get_signal_signature(fn: Callable[P, T]) -> list[SignalParameter]:
    """
    Extract parameter information from a signal handler function.

    Args:
        fn: The signal handler function

    Returns:
        List of SignalParameter objects

    Raises:
        ValueError: If parameters are not positional
    """
    sig = signature(fn)
    args = sig.parameters
    hints = get_type_hints(fn)
    params = []

    for name, param in args.items():
        # Filter out the self parameter for instance methods
        if param.name == "self":
            continue

        has_default = param.default != Parameter.empty
        default = param.default if has_default else None

        if param.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            type_hint = hints.get(name, None)
            params.append(SignalParameter(name, type_hint, has_default, default))
        else:
            raise ValueError(
                f"Signal handler '{fn.__qualname__}' parameter '{name}' must be positional, "
                f"got {param.kind.name}"
            )

    return params


_json_decoder = JSONDecoder(strict=False)


def _count_payload_values(payload: Payload) -> int:
    """Count the number of whitespace-delimited JSON values in a payload."""
    if not payload or not payload.data:
        return 0
    s = payload.data.decode()
    count = 0
    pos = 0
    while pos < len(s):
        while pos < len(s) and s[pos] in " \t\n\r":
            pos += 1
        if pos >= len(s):
            break
        try:
            _, end = _json_decoder.raw_decode(s, pos)
            count += 1
            pos = end
        except ValueError:
            break
    return count
