from collections.abc import Callable
from typing import Any, TypeVar

import grpc
from grpc.aio import Metadata, UnaryUnaryCall

RequestType = TypeVar("RequestType")
ResponseType = TypeVar("ResponseType")


class UnaryUnaryCallWrapper(UnaryUnaryCall[RequestType, ResponseType]):
    """Base class that delegates UnaryUnaryCall operations to a wrapped call."""

    def __init__(self, wrapped: UnaryUnaryCall[RequestType, ResponseType]):
        super().__init__()
        self._wrapped = wrapped

    async def initial_metadata(self) -> Metadata:
        return await self._wrapped.initial_metadata()

    async def trailing_metadata(self) -> Metadata:
        return await self._wrapped.trailing_metadata()

    async def code(self) -> grpc.StatusCode:
        return await self._wrapped.code()

    async def details(self) -> str:
        return await self._wrapped.details()

    async def wait_for_connection(self) -> None:
        await self._wrapped.wait_for_connection()

    def cancelled(self) -> bool:
        return self._wrapped.cancelled()

    def done(self) -> bool:
        return self._wrapped.done()

    def time_remaining(self) -> float | None:
        return self._wrapped.time_remaining()

    def cancel(self) -> bool:
        return self._wrapped.cancel()

    def add_done_callback(self, callback: Callable[[Any], None]) -> None:
        self._wrapped.add_done_callback(callback)
