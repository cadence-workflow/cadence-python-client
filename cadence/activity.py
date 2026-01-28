import inspect
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta, datetime
from typing import (
    Iterator,
    TypedDict,
    Unpack,
    Callable,
    ParamSpec,
    TypeVar,
    overload,
    Awaitable,
    Self,
    Protocol,
    cast,
    Union,
    Any,
    Concatenate,
    Generic,
    Type,
)

from cadence import Client
from cadence._internal.activity._definition import (
    AsyncImpl,
    SyncImpl,
    AsyncMethodImpl,
    SyncMethodImpl,
)
from cadence._internal.fn_signature import FnSignature
from cadence.workflow import ActivityOptions


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


class ActivityDefinitionOptions(TypedDict, total=False):
    name: str


T = TypeVar("T", contravariant=True)
P = ParamSpec("P")
R = TypeVar("R", covariant=True)


class ActivityDefinition(Protocol[P, R]):
    @property
    def name(self) -> str: ...

    def with_options(self, **kwargs: Unpack[ActivityOptions]) -> Self: ...

    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> R: ...


class _SyncActivityDefinition(ActivityDefinition[P, R], Protocol):
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...


class _AsyncActivityDefinition(ActivityDefinition[P, R], Protocol):
    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...


class _SyncActivityMethodDefinition(ActivityDefinition[P, R], Protocol[T, P, R]):
    def __call__(self, original_self: T, *args: P.args, **kwargs: P.kwargs) -> R: ...

    @overload
    def __get__(
        self, instance: None, owner: Type[T]
    ) -> "_SyncActivityMethodDefinition[T, P, R]": ...
    @overload
    def __get__(self, instance: T, owner: Type[T]) -> _SyncActivityDefinition[P, R]: ...
    def __get__(
        self, instance: T | None, owner: Type[T]
    ) -> _SyncActivityDefinition[P, R] | Self: ...


class _AsyncActivityMethodDefinition(ActivityDefinition[P, R], Protocol[T, P, R]):
    async def __call__(
        self, original_self: T, *args: P.args, **kwargs: P.kwargs
    ) -> R: ...

    @overload
    def __get__(
        self, instance: None, owner: Type[T]
    ) -> "_AsyncActivityMethodDefinition[T, P, R]": ...
    @overload
    def __get__(
        self, instance: T, owner: Type[T]
    ) -> _AsyncActivityDefinition[P, R]: ...
    def __get__(
        self, instance: T | None, owner: Type[T]
    ) -> _AsyncActivityDefinition[P, R] | Self: ...


_T1 = TypeVar("_T1", contravariant=True)
_P1 = ParamSpec("_P1")
_R1 = TypeVar("_R1")
_T2 = TypeVar("_T2", contravariant=True)
_P2 = ParamSpec("_P2")
_R2 = TypeVar("_R2")


class ActivityDecorator:
    def __init__(
        self,
        options: ActivityDefinitionOptions,
        callback_fn: Callable[[ActivityDefinition[Any, Any]], None] | None = None,
    ) -> None:
        self._options = options
        self._callback_fn = callback_fn

    @overload
    def __call__(
        self, fn: Callable[P, Awaitable[R]]
    ) -> _AsyncActivityDefinition[P, R]: ...
    @overload
    def __call__(self, fn: Callable[P, R]) -> _SyncActivityDefinition[P, R]: ...
    def __call__(
        self, fn: Union[Callable[_P1, Awaitable[_R1]], Callable[_P2, _R2]]
    ) -> Union[_AsyncActivityDefinition[_P1, _R1], _SyncActivityDefinition[_P2, _R2]]:
        name = self._options.get("name", fn.__qualname__)
        if inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(fn.__call__):  # type: ignore
            async_fn = cast(Callable[_P1, Awaitable[_R1]], fn)
            async_def: _AsyncActivityDefinition[_P1, _R1] = AsyncImpl[_P1, _R1](
                async_fn, name, FnSignature.of(async_fn)
            )
            if self._callback_fn is not None:
                self._callback_fn(async_def)
            return async_def
        sync_fn = cast(Callable[_P2, _R2], fn)
        sync_def: _SyncActivityDefinition[_P2, _R2] = SyncImpl[_P2, _R2](
            sync_fn, name, FnSignature.of(fn)
        )
        if self._callback_fn is not None:
            self._callback_fn(sync_def)
        return sync_def


@overload
def defn(fn: Callable[P, Awaitable[R]]) -> _AsyncActivityDefinition[P, R]: ...


@overload
def defn(fn: Callable[P, R]) -> _SyncActivityDefinition[P, R]: ...


@overload
def defn(**kwargs: Unpack[ActivityDefinitionOptions]) -> ActivityDecorator: ...


def defn(
    fn: Union[Callable[_P1, _R1], Callable[_P2, Awaitable[_R2]], None] = None,
    **kwargs: Unpack[ActivityDefinitionOptions],
) -> Union[
    ActivityDecorator,
    _SyncActivityDefinition[_P1, _R1],
    _AsyncActivityDefinition[_P2, _R2],
]:
    options = ActivityDefinitionOptions(**kwargs)
    if fn is not None:
        return ActivityDecorator(options)(fn)

    return ActivityDecorator(options)


class _ActivityMethodDecorator:
    def __init__(
        self,
        options: ActivityDefinitionOptions,
        callback_fn: Callable[[ActivityDefinition[Any, Any]], None] | None = None,
    ) -> None:
        self._options = options
        self._callback_fn = callback_fn

    @overload
    def __call__(
        self, fn: Callable[Concatenate[T, P], Awaitable[R]]
    ) -> _AsyncActivityMethodDefinition[T, P, R]: ...
    @overload
    def __call__(
        self, fn: Callable[Concatenate[T, P], R]
    ) -> _SyncActivityMethodDefinition[T, P, R]: ...
    def __call__(
        self,
        fn: Union[
            Callable[Concatenate[_T1, _P1], Awaitable[_R1]],
            Callable[Concatenate[_T2, _P2], _R2],
        ],
    ) -> Union[
        _AsyncActivityMethodDefinition[_T1, _P1, _R1],
        _SyncActivityMethodDefinition[_T2, _P2, _R2],
    ]:
        name = self._options.get("name", fn.__qualname__)
        if inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(fn.__call__):  # type: ignore
            async_fn = cast(Callable[Concatenate[_T1, _P1], Awaitable[_R1]], fn)
            async_def: _AsyncActivityMethodDefinition[_T1, _P1, _R1] = AsyncMethodImpl[
                _T1, _P1, _R1
            ](async_fn, name, FnSignature.of(async_fn))
            if self._callback_fn is not None:
                self._callback_fn(async_def)
            return async_def
        sync_fn = cast(Callable[Concatenate[_T2, _P2], _R2], fn)
        sync_def: _SyncActivityMethodDefinition[_T2, _P2, _R2] = SyncMethodImpl[
            _T2, _P2, _R2
        ](sync_fn, name, FnSignature.of(fn))
        if self._callback_fn is not None:
            self._callback_fn(sync_def)
        return sync_def


@overload
def method(
    fn: Callable[Concatenate[T, P], Awaitable[R]],
) -> _AsyncActivityMethodDefinition[T, P, R]: ...


@overload
def method(
    fn: Callable[Concatenate[T, P], R],
) -> _SyncActivityMethodDefinition[T, P, R]: ...


@overload
def method(**kwargs: Unpack[ActivityDefinitionOptions]) -> _ActivityMethodDecorator: ...


def method(
    fn: Union[
        Callable[Concatenate[_T1, _P1], _R1],
        Callable[Concatenate[_T2, _P2], Awaitable[_R2]],
        None,
    ] = None,
    **kwargs: Unpack[ActivityDefinitionOptions],
) -> Union[
    _ActivityMethodDecorator,
    _SyncActivityMethodDefinition[_T1, _P1, _R1],
    _AsyncActivityMethodDefinition[_T2, _P2, _R2],
]:
    options = ActivityDefinitionOptions(**kwargs)
    if fn is not None:
        return _ActivityMethodDecorator(options)(fn)

    return _ActivityMethodDecorator(options)


class _OverrideDecorator(Generic[T, P, R]):
    def __init__(self, definition: ActivityDefinition[P, R]):
        self._definition = definition

    @overload
    def __call__(
        self, fn: Callable[Concatenate[Any, P], Awaitable[R]]
    ) -> _AsyncActivityMethodDefinition[T, P, R]: ...
    @overload
    def __call__(
        self, fn: Callable[Concatenate[Any, P], R]
    ) -> _SyncActivityMethodDefinition[T, P, R]: ...
    def __call__(
        self,
        fn: Union[
            Callable[Concatenate[Any, P], R],
            Callable[Concatenate[Any, P], Awaitable[R]],
        ],
    ) -> Union[
        _SyncActivityMethodDefinition[T, P, R], _AsyncActivityMethodDefinition[T, P, R]
    ]:
        return self._definition.rebind(fn)  # type: ignore


@overload
def override(
    definition: _AsyncActivityMethodDefinition[T, P, R],
) -> _OverrideDecorator[T, P, R]: ...
@overload
def override(
    definition: _SyncActivityMethodDefinition[T, P, R],
) -> _OverrideDecorator[T, P, R]: ...
def override(
    definition: Union[
        _AsyncActivityMethodDefinition[T, _P1, _R1],
        _SyncActivityMethodDefinition[T, _P2, _R2],
    ],
) -> Union[_OverrideDecorator[T, _P1, _R1], _OverrideDecorator[T, _P2, _R2]]:
    if inspect.iscoroutinefunction(definition.__call__):  # type: ignore
        async_def = cast(ActivityDefinition[_P1, _R1], definition)
        return _OverrideDecorator[T, _P1, _R1](async_def)
    else:
        sync_def = cast(ActivityDefinition[_P2, _R2], definition)
        return _OverrideDecorator[T, _P2, _R2](sync_def)
