import asyncio
import time
from collections.abc import Callable, Generator
from typing import Any, TypeVar

from grpc import StatusCode
from grpc.aio import ClientCallDetails, UnaryUnaryCall, UnaryUnaryClientInterceptor

from cadence._internal.rpc.call import UnaryUnaryCallWrapper
from cadence.error import (
    CadenceRpcError,
    DomainAlreadyExistsError,
    EntityNotExistsError,
    QueryFailedError,
    WorkflowExecutionAlreadyCompletedError,
    WorkflowExecutionAlreadyStartedError,
)
from cadence.metrics.constants import (
    CADENCE_ERROR,
    CADENCE_INVALID_REQUEST,
    CADENCE_LATENCY,
    CADENCE_METRICS_PREFIX,
    CADENCE_REQUEST,
)
from cadence.metrics.metrics import MetricsEmitter, duration_from_nanoseconds

RequestType = TypeVar("RequestType")
ResponseType = TypeVar("ResponseType")

_INVALID_REQUEST_ERRORS = (
    DomainAlreadyExistsError,
    EntityNotExistsError,
    QueryFailedError,
    WorkflowExecutionAlreadyCompletedError,
    WorkflowExecutionAlreadyStartedError,
)


def _metric_name(operation: str, metric: str) -> str:
    return f"{CADENCE_METRICS_PREFIX}{operation}.{metric}"


def _is_invalid_request(error: BaseException) -> bool:
    return isinstance(error, _INVALID_REQUEST_ERRORS) or (
        isinstance(error, CadenceRpcError) and error.code == StatusCode.INVALID_ARGUMENT
    )


def _record_rpc_completion(
    emitter: MetricsEmitter,
    operation: str,
    start_ns: int,
    error: BaseException | None = None,
) -> None:
    elapsed = duration_from_nanoseconds(time.monotonic_ns() - start_ns)
    emitter.histogram(_metric_name(operation, CADENCE_LATENCY), elapsed)
    if error is not None:
        outcome = (
            CADENCE_INVALID_REQUEST if _is_invalid_request(error) else CADENCE_ERROR
        )
        emitter.counter(_metric_name(operation, outcome))


def _extract_method_name(method: bytes | str) -> str:
    if isinstance(method, bytes):
        method = method.decode("utf-8", errors="replace")
    return method.rsplit("/", 1)[-1]


class _MetricsUnaryUnaryCall(UnaryUnaryCallWrapper[RequestType, ResponseType]):
    def __init__(
        self,
        wrapped: UnaryUnaryCall[RequestType, ResponseType],
        operation: str,
        start_ns: int,
        emitter: MetricsEmitter,
    ):
        super().__init__(wrapped)
        self._operation = operation
        self._start_ns = start_ns
        self._emitter = emitter
        self._recorded = False
        self._emitter.counter(_metric_name(operation, CADENCE_REQUEST))

    def _record_completion(self, error: BaseException | None = None) -> None:
        if self._recorded:
            return
        self._recorded = True
        _record_rpc_completion(
            self._emitter, self._operation, self._start_ns, error=error
        )

    def __await__(self) -> Generator[Any, None, ResponseType]:
        try:
            response = yield from self._wrapped.__await__()  # type: ResponseType
        except (CadenceRpcError, asyncio.CancelledError) as error:
            self._record_completion(error)
            raise
        else:
            self._record_completion()
            return response


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
        rpc_call = await continuation(client_call_details, request)
        return _MetricsUnaryUnaryCall(rpc_call, operation, start_ns, self._emitter)
