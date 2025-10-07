from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import update_wrapper
from inspect import signature, Parameter
from typing import Iterator, Callable, TypeVar, ParamSpec, Generic, TypedDict, Unpack, overload, get_type_hints, Type, Any

from cadence.client import Client


@dataclass(frozen=True)
class WorkflowParameter:
    """Parameter information for a workflow function."""
    name: str
    type_hint: Type | None
    default_value: Any | None


class WorkflowDefinitionOptions(TypedDict, total=False):
    """Options for defining a workflow."""
    name: str


P = ParamSpec('P')
T = TypeVar('T')


class WorkflowDefinition(Generic[P, T]):
    """
    Definition of a workflow function with metadata.

    Similar to ActivityDefinition but for workflows.
    Provides type safety and metadata for workflow functions.
    """

    def __init__(self, wrapped: Callable[P, T], name: str, params: list[WorkflowParameter]):
        self._wrapped = wrapped
        self._name = name
        self._params = params
        update_wrapper(self, wrapped)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        return self._wrapped(*args, **kwargs)

    @property
    def name(self) -> str:
        """Get the workflow name."""
        return self._name

    @property
    def params(self) -> list[WorkflowParameter]:
        """Get the workflow parameters."""
        return self._params

    @property
    def fn(self) -> Callable[P, T]:
        """Get the underlying workflow function."""
        return self._wrapped

    @classmethod
    def wrap(cls, fn: Callable[P, T], opts: WorkflowDefinitionOptions) -> 'WorkflowDefinition[P, T]':
        """
        Wrap a function as a WorkflowDefinition.

        Args:
            fn: The workflow function to wrap
            opts: Options for the workflow definition

        Returns:
            A WorkflowDefinition instance
        """
        name = fn.__qualname__
        if "name" in opts and opts["name"]:
            name = opts["name"]

        params = _get_workflow_params(fn)
        return cls(fn, name, params)


WorkflowDecorator = Callable[[Callable[P, T]], WorkflowDefinition[P, T]]


@overload
def defn(fn: Callable[P, T]) -> WorkflowDefinition[P, T]:
    ...


@overload
def defn(**kwargs: Unpack[WorkflowDefinitionOptions]) -> WorkflowDecorator:
    ...


def defn(fn: Callable[P, T] | None = None, **kwargs: Unpack[WorkflowDefinitionOptions]) -> WorkflowDecorator | WorkflowDefinition[P, T]:
    """
    Decorator to define a workflow function.

    Usage:
        @defn
        def my_workflow(input_data: str) -> str:
            return f"processed: {input_data}"

        @defn(name="custom_workflow_name")
        def my_other_workflow(input_data: str) -> str:
            return f"custom: {input_data}"

    Args:
        fn: The workflow function (when used without parentheses)
        **kwargs: Workflow definition options

    Returns:
        Either a WorkflowDefinition (direct decoration) or a decorator function
    """
    opts = WorkflowDefinitionOptions(**kwargs)

    def decorator(inner_fn: Callable[P, T]) -> WorkflowDefinition[P, T]:
        return WorkflowDefinition.wrap(inner_fn, opts)

    if fn is not None:
        return decorator(fn)

    return decorator


def _get_workflow_params(fn: Callable) -> list[WorkflowParameter]:
    """Extract parameter information from a workflow function."""
    args = signature(fn).parameters
    hints = get_type_hints(fn)
    result = []
    for name, param in args.items():
        # Filter out self parameter
        if param.name == "self":
            continue
        default = None
        if param.default != Parameter.empty:
            default = param.default
        if param.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            type_hint = hints.get(name, None)
            result.append(WorkflowParameter(name, type_hint, default))
        else:
            raise ValueError(f"Parameters must be positional. {name} is {param.kind}, and not valid")

    return result


@dataclass
class WorkflowInfo:
    workflow_type: str
    workflow_domain: str
    workflow_id: str
    workflow_run_id: str

class WorkflowContext(ABC):
    _var: ContextVar['WorkflowContext'] = ContextVar("workflow")

    @abstractmethod
    def info(self) -> WorkflowInfo:
        ...

    @abstractmethod
    def client(self) -> Client:
        ...

    @contextmanager
    def _activate(self) -> Iterator[None]:
        token = WorkflowContext._var.set(self)
        yield None
        WorkflowContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return WorkflowContext._var.get(None) is not None

    @staticmethod
    def get() -> 'WorkflowContext':
        return WorkflowContext._var.get()
