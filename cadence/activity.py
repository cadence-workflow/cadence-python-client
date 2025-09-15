import inspect
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta, datetime
from enum import Enum
from functools import update_wrapper
from inspect import signature, Parameter
from typing import Iterator, TypedDict, Unpack, Callable, Type, ParamSpec, TypeVar, Generic, get_type_hints, \
    Any, overload

from cadence import Client


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
    _var: ContextVar['ActivityContext'] = ContextVar("activity")

    @abstractmethod
    def info(self) -> ActivityInfo:
        ...

    @abstractmethod
    def client(self) -> Client:
        ...

    @contextmanager
    def _activate(self) -> Iterator[None]:
        token = ActivityContext._var.set(self)
        yield None
        ActivityContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return ActivityContext._var.get(None) is not None

    @staticmethod
    def get() -> 'ActivityContext':
        return ActivityContext._var.get()


@dataclass(frozen=True)
class ActivityParameter:
    name: str
    type_hint: Type | None
    default_value: Any | None

class ExecutionStrategy(Enum):
    ASYNC = "async"
    THREAD_POOL = "thread_pool"

class ActivityDefinitionOptions(TypedDict, total=False):
    name: str

P = ParamSpec('P')
T = TypeVar('T')

class ActivityDefinition(Generic[P, T]):
    def __init__(self, wrapped: Callable[P, T], name: str, strategy: ExecutionStrategy, params: list[ActivityParameter]):
        self._wrapped = wrapped
        self._name = name
        self._strategy = strategy
        self._params = params
        update_wrapper(self, wrapped)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        return self._wrapped(*args, **kwargs)

    @property
    def name(self) -> str:
        return self._name

    @property
    def strategy(self) -> ExecutionStrategy:
        return self._strategy

    @property
    def params(self) -> list[ActivityParameter]:
        return self._params

    @staticmethod
    def wrap(fn: Callable[P, T], opts: ActivityDefinitionOptions) -> 'ActivityDefinition[P, T]':
        name = fn.__qualname__
        if "name" in opts and opts["name"]:
            name = opts["name"]

        strategy = ExecutionStrategy.THREAD_POOL
        if inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(fn.__call__): # type: ignore
            strategy = ExecutionStrategy.ASYNC

        params = _get_params(fn)
        return ActivityDefinition(fn, name, strategy, params)


ActivityDecorator = Callable[[Callable[P, T]], ActivityDefinition[P, T]]

@overload
def defn(fn: Callable[P, T]) -> ActivityDefinition[P, T]:
    ...

@overload
def defn(**kwargs: Unpack[ActivityDefinitionOptions]) -> ActivityDecorator:
    ...

def defn(fn: Callable[P, T] | None = None, **kwargs: Unpack[ActivityDefinitionOptions]) -> ActivityDecorator | ActivityDefinition[P, T]:
    options = ActivityDefinitionOptions(**kwargs)
    def decorator(inner_fn: Callable[P, T]) -> ActivityDefinition[P, T]:
        return ActivityDefinition.wrap(inner_fn, options)

    if fn is not None:
        return decorator(fn)

    return decorator


def _get_params(fn: Callable) -> list[ActivityParameter]:
    args = signature(fn).parameters
    hints = get_type_hints(fn)
    result = []
    for name, param in args.items():
        # "unbound functions" aren't a thing in the Python spec. Filter out the self parameter and hope they followed
        # the convention.
        if param.name == "self":
            continue
        default = None
        if param.default != Parameter.empty:
            default = param.default
        if param.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            type_hint = hints.get(name, None)
            result.append(ActivityParameter(name, type_hint, default))

        else:
            raise ValueError(f"Parameters must be positional. {name} is {param.kind}, and not valid")

    return result
