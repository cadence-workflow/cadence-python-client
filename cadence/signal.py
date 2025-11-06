"""
Signal definition and registration for Cadence workflows.

This module provides functionality to define and register signal handlers
for workflows, similar to ActivityDefinition but for signals.
"""

import inspect
from dataclasses import dataclass
from functools import update_wrapper
from inspect import Parameter, signature
from typing import (
    Callable,
    Generic,
    ParamSpec,
    Type,
    TypeVar,
    TypedDict,
    Unpack,
    overload,
    get_type_hints,
    Any,
)

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
        is_async: bool,
    ):
        self._wrapped = wrapped
        self._name = name
        self._params = params
        self._is_async = is_async
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
    def is_async(self) -> bool:
        """Check if the signal handler is async."""
        return self._is_async

    @property
    def wrapped(self) -> Callable[P, T]:
        """Get the wrapped signal handler function."""
        return self._wrapped

    @staticmethod
    def wrap(
        fn: Callable[P, T], opts: SignalDefinitionOptions
    ) -> "SignalDefinition[P, T]":
        """
        Wrap a function as a SignalDefinition.

        Args:
            fn: The signal handler function to wrap
            opts: Options for the signal definition

        Returns:
            A SignalDefinition instance

        Raises:
            ValueError: If name is not provided in options or return type is not None
        """
        name = opts.get("name") or fn.__qualname__
        is_async = inspect.iscoroutinefunction(fn)
        params = _get_signal_signature(fn)
        _validate_signal_return_type(fn)

        return SignalDefinition(fn, name, params, is_async)


SignalDecorator = Callable[[Callable[P, T]], SignalDefinition[P, T]]


@overload
def defn(fn: Callable[P, T]) -> SignalDefinition[P, T]: ...


@overload
def defn(**kwargs: Unpack[SignalDefinitionOptions]) -> SignalDecorator: ...


def defn(
    fn: Callable[P, T] | None = None, **kwargs: Unpack[SignalDefinitionOptions]
) -> SignalDecorator | SignalDefinition[P, T]:
    """
    Decorator to define a signal handler.

    Can be used with or without parentheses:
        @signal.defn(name="approval")
        async def handle_approval(self, approved: bool):
            ...

        @signal.defn(name="approval")
        def handle_approval(self, approved: bool):
            ...

    Args:
        fn: The signal handler function to decorate
        **kwargs: Options for the signal definition (name is required)

    Returns:
        The decorated function as a SignalDefinition instance

    Raises:
        ValueError: If name is not provided
    """
    options = SignalDefinitionOptions(**kwargs)

    def decorator(inner_fn: Callable[P, T]) -> SignalDefinition[P, T]:
        return SignalDefinition.wrap(inner_fn, options)

    if fn is not None:
        return decorator(fn)

    return decorator


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

        if ret_type is not None and ret_type is not inspect.Signature.empty:
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
