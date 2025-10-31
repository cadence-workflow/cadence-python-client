import inspect
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta, datetime
from enum import Enum
from functools import update_wrapper
from inspect import signature, Parameter
from typing import (
    Iterator,
    TypedDict,
    Unpack,
    Callable,
    Type,
    ParamSpec,
    TypeVar,
    Generic,
    get_type_hints,
    Any,
    overload,
    Tuple,
    Sequence,
)

from cadence import Client
from cadence.workflow import WorkflowContext, ActivityOptions, execute_activity


@dataclass(frozen=True)
class ActivityInfo:
    task_token: bytes
    workflow_type: str
    workflow_domain: str
    workflow_id: str
    workflow_run_id: str
    activity_id: str
    activity_type: str
    task_list: str
    heartbeat_timeout: timedelta
    scheduled_timestamp: datetime
    started_timestamp: datetime
    start_to_close_timeout: timedelta
    attempt: int


def client() -> Client:
    return ActivityContext.get().client()


def in_activity() -> bool:
    return ActivityContext.is_set()


def info() -> ActivityInfo:
    return ActivityContext.get().info()


class ActivityContext(ABC):
    _var: ContextVar["ActivityContext"] = ContextVar("activity")

    @abstractmethod
    def info(self) -> ActivityInfo: ...

    @abstractmethod
    def client(self) -> Client: ...

    @contextmanager
    def _activate(self) -> Iterator[None]:
        token = ActivityContext._var.set(self)
        yield None
        ActivityContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return ActivityContext._var.get(None) is not None

    @staticmethod
    def get() -> "ActivityContext":
        return ActivityContext._var.get()


@dataclass(frozen=True)
class ActivityParameter:
    name: str
    type_hint: Type | None
    has_default: bool
    default_value: Any


class ExecutionStrategy(Enum):
    ASYNC = "async"
    THREAD_POOL = "thread_pool"


class ActivityDefinitionOptions(TypedDict, total=False):
    name: str


P = ParamSpec("P")
T = TypeVar("T")


class ActivityDefinition(Generic[P, T]):
    def __init__(
        self,
        wrapped: Callable[P, T],
        name: str,
        strategy: ExecutionStrategy,
        params: list[ActivityParameter],
        result_type: Type[T],
    ):
        self._wrapped = wrapped
        self._name = name
        self._strategy = strategy
        self._params = params
        self._result_type = result_type
        self._execution_options = ActivityOptions()
        update_wrapper(self, wrapped)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        if WorkflowContext.is_set():
            # If the original function is async then this is fine
            # If it's not async then this is invalid typing, but still allowed
            # Users can use execute as a guaranteed type safe option if the function is sync
            return self.execute(*args, **kwargs)  # type: ignore
        return self._wrapped(*args, **kwargs)

    def with_options(
        self, **kwargs: Unpack[ActivityOptions]
    ) -> "ActivityDefinition[P, T]":
        res = ActivityDefinition(
            self._wrapped, self._name, self.strategy, self.params, self.result_type
        )
        new_opts = self._execution_options.copy()
        new_opts.update(kwargs)
        res._execution_options = new_opts
        return res

    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> T:
        return await execute_activity(
            self.name,
            self.result_type,
            *_to_parameters(self.params, args, kwargs),
            **self._execution_options,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def strategy(self) -> ExecutionStrategy:
        return self._strategy

    @property
    def params(self) -> list[ActivityParameter]:
        return self._params

    @property
    def result_type(self) -> Type[T]:
        return self._result_type

    @staticmethod
    def wrap(
        fn: Callable[P, T], opts: ActivityDefinitionOptions
    ) -> "ActivityDefinition[P, T]":
        name = fn.__qualname__
        if "name" in opts and opts["name"]:
            name = opts["name"]

        strategy = ExecutionStrategy.THREAD_POOL
        if inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(fn.__call__):  # type: ignore
            strategy = ExecutionStrategy.ASYNC

        params, result_type = _get_signature(fn)
        return ActivityDefinition(fn, name, strategy, params, result_type)


ActivityDecorator = Callable[[Callable[P, T]], ActivityDefinition[P, T]]


@overload
def defn(fn: Callable[P, T]) -> ActivityDefinition[P, T]: ...


@overload
def defn(**kwargs: Unpack[ActivityDefinitionOptions]) -> ActivityDecorator: ...


def defn(
    fn: Callable[P, T] | None = None, **kwargs: Unpack[ActivityDefinitionOptions]
) -> ActivityDecorator | ActivityDefinition[P, T]:
    options = ActivityDefinitionOptions(**kwargs)

    def decorator(inner_fn: Callable[P, T]) -> ActivityDefinition[P, T]:
        return ActivityDefinition.wrap(inner_fn, options)

    if fn is not None:
        return decorator(fn)

    return decorator


def _get_signature(fn: Callable[P, T]) -> Tuple[list[ActivityParameter], Type[T]]:
    sig = signature(fn)
    args = sig.parameters
    hints = get_type_hints(fn)
    params = []
    for name, param in args.items():
        # "unbound functions" aren't a thing in the Python spec. We don't have a way to determine whether the function
        # is part of a class or is standalone.
        # Filter out the self parameter and hope they followed the convention.
        if param.name == "self":
            continue
        default = None
        has_default = False
        if param.default != Parameter.empty:
            default = param.default
            has_default = param.default is not None
        if param.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            type_hint = hints.get(name, None)
            params.append(ActivityParameter(name, type_hint, has_default, default))
        else:
            raise ValueError(
                f"Parameters must be positional. {name} is {param.kind}, and not valid"
            )

    # Treat unspecified return type
    return_type = hints.get("return", dict)

    return params, return_type


def _to_parameters(
    params: list[ActivityParameter], args: Sequence[Any], kwargs: dict[str, Any]
) -> list[Any]:
    result: list[Any] = []
    for value, param_spec in zip(args, params):
        result.append(value)

    i = len(result)
    while i < len(params):
        param = params[i]
        if param.name not in kwargs and not param.has_default:
            raise ValueError(f"Missing parameter: {param.name}")

        value = kwargs.pop(param.name, param.default_value)
        result.append(value)
        i = i + 1

    if len(kwargs) > 0:
        raise ValueError(f"Unexpected keyword arguments: {kwargs}")

    return result
