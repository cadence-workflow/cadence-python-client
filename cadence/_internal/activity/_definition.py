import abc
from abc import ABC
from enum import Enum
from functools import update_wrapper, partial
from typing import (
    Generic,
    Callable,
    Unpack,
    Self,
    ParamSpec,
    TypeVar,
    Awaitable,
    cast,
    Concatenate,
)

from cadence._internal.fn_signature import FnSignature
from cadence.workflow import ActivityOptions, WorkflowContext, execute_activity

T = TypeVar("T")
P = ParamSpec("P")
R = TypeVar("R")


class ExecutionStrategy(Enum):
    ASYNC = "async"
    THREAD_POOL = "thread_pool"


class BaseDefinition(ABC, Generic[P, R]):
    def __init__(
        self,
        name: str,
        wrapped: Callable,
        strategy: ExecutionStrategy,
        signature: FnSignature,
    ):
        self._name = name
        self._wrapped = wrapped
        self._strategy = strategy
        self._signature = signature
        self._execution_options = ActivityOptions()

    @property
    def strategy(self) -> ExecutionStrategy:
        return self._strategy

    @property
    def signature(self) -> FnSignature:
        return self._signature

    @property
    def impl_fn(self) -> Callable:
        return self._wrapped

    @property
    def name(self) -> str:
        return self._name

    @abc.abstractmethod
    def clone(self) -> Self: ...

    def rebind(self, fn: Callable) -> Self:
        res = self.clone()
        res._wrapped = fn
        return res

    def with_options(self, **kwargs: Unpack[ActivityOptions]) -> Self:
        res = self.clone()
        new_opts = self._execution_options.copy()
        new_opts.update(kwargs)
        res._execution_options = new_opts
        return res

    async def execute(self, *args: P.args, **kwargs: P.kwargs) -> R:
        result_type = cast(type[R], self._signature.return_type)
        return await execute_activity(
            self._name,
            result_type,
            *self._signature.params_from_call(args, kwargs),
            **self._execution_options,
        )


class SyncImpl(BaseDefinition[P, R]):
    def __init__(
        self,
        wrapped: Callable[P, R],
        name: str,
        signature: FnSignature,
    ):
        super().__init__(name, wrapped, ExecutionStrategy.THREAD_POOL, signature)
        update_wrapper(self, wrapped)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        if WorkflowContext.is_set():
            raise RuntimeError(
                "Attempting to invoke sync function in workflow. Use execute"
            )
        return self._wrapped(*args, **kwargs)  # type: ignore

    def clone(self) -> "SyncImpl[P, R]":
        return SyncImpl[P, R](self._wrapped, self._name, self._signature)


class SyncMethodImpl(BaseDefinition[P, R], Generic[T, P, R]):
    def __init__(
        self,
        wrapped: Callable[Concatenate[T, P], R],
        name: str,
        signature: FnSignature,
    ):
        super().__init__(name, wrapped, ExecutionStrategy.THREAD_POOL, signature)
        update_wrapper(self, wrapped)

    def __get__(self, instance, owner):
        if instance is None:
            return self
        # If we bound the method to an instance, then drop the self parameter. It's a normal function again
        return SyncImpl[P, R](
            partial(self._wrapped, instance), self.name, self._signature
        )

    def __call__(self, original_self: T, *args: P.args, **kwargs: P.kwargs) -> R:
        if WorkflowContext.is_set():
            raise RuntimeError(
                "Attempting to invoke sync function in workflow. Use execute"
            )
        return self._wrapped(original_self, *args, **kwargs)  # type: ignore

    def clone(self) -> "SyncMethodImpl[T, P, R]":
        return SyncMethodImpl[T, P, R](self._wrapped, self._name, self._signature)


class AsyncImpl(BaseDefinition[P, R]):
    def __init__(
        self,
        wrapped: Callable[P, Awaitable[R]],
        name: str,
        signature: FnSignature,
    ):
        super().__init__(name, wrapped, ExecutionStrategy.ASYNC, signature)
        update_wrapper(self, wrapped)

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        if WorkflowContext.is_set():
            return await self.execute(*args, **kwargs)  # type: ignore
        return await self._wrapped(*args, **kwargs)  # type: ignore

    def clone(self) -> "AsyncImpl[P, R]":
        return AsyncImpl[P, R](self._wrapped, self._name, self._signature)


class AsyncMethodImpl(BaseDefinition[P, R], Generic[T, P, R]):
    def __init__(
        self,
        wrapped: Callable[Concatenate[T, P], Awaitable[R]],
        name: str,
        signature: FnSignature,
    ):
        super().__init__(name, wrapped, ExecutionStrategy.ASYNC, signature)
        update_wrapper(self, wrapped)

    def __get__(self, instance, owner):
        if instance is None:
            return self
        # If we bound the method to an instance, then drop the self parameter. It's a normal function again
        return AsyncImpl[P, R](
            partial(self._wrapped, instance), self.name, self._signature
        )

    async def __call__(self, original_self: T, *args: P.args, **kwargs: P.kwargs) -> R:
        if WorkflowContext.is_set():
            return await self.execute(*args, **kwargs)  # type: ignore
        return await self._wrapped(original_self, *args, **kwargs)  # type: ignore

    def clone(self) -> "AsyncMethodImpl[T, P, R]":
        return AsyncMethodImpl[T, P, R](self._wrapped, self._name, self._signature)
