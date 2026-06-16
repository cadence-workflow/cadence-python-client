import time
from typing import Any, Callable, Generator, Optional, TypeVar

from grpc.aio import UnaryUnaryClientInterceptor, ClientCallDetails, UnaryUnaryCall

from cadence.metrics.constants import (
    CADENCE_METRICS_PREFIX,
    CADENCE_ERROR,
    CADENCE_LATENCY,
    CADENCE_REQUEST,
)
from cadence.metrics.metrics import MetricsEmitter, duration_from_nanoseconds

RequestType = TypeVar("RequestType")
ResponseType = TypeVar("ResponseType")


def _record_rpc_metrics(
    emitter: MetricsEmitter, operation: str, start_ns: int, failed: bool = False
) -> None:
    scope = f"{CADENCE_METRICS_PREFIX}{operation}."
    elapsed = duration_from_nanoseconds(time.monotonic_ns() - start_ns)
    emitter.counter(f"{scope}{CADENCE_REQUEST}")
    emitter.histogram(f"{scope}{CADENCE_LATENCY}", elapsed)
    if failed:
        emitter.counter(f"{scope}{CADENCE_ERROR}")


def _extract_method_name(method: bytes | str) -> str:
    if isinstance(method, bytes):
        method = method.decode("utf-8", errors="replace")
    return method.rsplit("/", 1)[-1]


class _MetricsUnaryUnaryCall(UnaryUnaryCall[RequestType, ResponseType]):
    def __init__(
        self,
        wrapped: UnaryUnaryCall[RequestType, ResponseType],
        operation: str,
        start_ns: int,
        emitter: MetricsEmitter,
    ):
        super().__init__()
        self._wrapped = wrapped
        self._operation = operation
        self._start_ns = start_ns
        self._emitter = emitter

    def __await__(self) -> Generator[Any, None, ResponseType]:
        failed = False
        try:
            return (yield from self._wrapped.__await__())
        except Exception:
            failed = True
            raise
        finally:
            _record_rpc_metrics(
                self._emitter, self._operation, self._start_ns, failed
            )

    async def initial_metadata(self):
        return await self._wrapped.initial_metadata()

    async def trailing_metadata(self):
        return await self._wrapped.trailing_metadata()

    async def code(self):
        return await self._wrapped.code()

    async def details(self):
        return await self._wrapped.details()

    async def wait_for_connection(self) -> None:
        await self._wrapped.wait_for_connection()

    def cancelled(self) -> bool:
        return self._wrapped.cancelled()

    def done(self) -> bool:
        return self._wrapped.done()

    def time_remaining(self) -> Optional[float]:
        return self._wrapped.time_remaining()

    def cancel(self) -> bool:
        return self._wrapped.cancel()

    def add_done_callback(self, callback: Callable[[Any], None]) -> None:
        self._wrapped.add_done_callback(callback)


class MetricsInterceptor(UnaryUnaryClientInterceptor):
    def __init__(self, emitter: MetricsEmitter):
        self._emitter = emitter

    async def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, Any], Any],
        client_call_details: ClientCallDetails,
        request: Any,
    ) -> Any:
        start_ns = time.monotonic_ns()
        operation = _extract_method_name(client_call_details.method)
        try:
            rpc_call = await continuation(client_call_details, request)
        except Exception:
            _record_rpc_metrics(self._emitter, operation, start_ns, failed=True)
            raise
        return _MetricsUnaryUnaryCall(rpc_call, operation, start_ns, self._emitter)
