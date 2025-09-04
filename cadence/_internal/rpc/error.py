from typing import Callable, Any, Optional, Generator, TypeVar

import grpc
from google.rpc.status_pb2 import Status # type: ignore
from grpc.aio import UnaryUnaryClientInterceptor, ClientCallDetails, AioRpcError, UnaryUnaryCall, Metadata
from grpc_status.rpc_status import from_call # type: ignore

from cadence.api.v1 import error_pb2
from cadence import error


RequestType = TypeVar("RequestType")
ResponseType = TypeVar("ResponseType")
DoneCallbackType = Callable[[Any], None]


# A UnaryUnaryCall is an awaitable type returned by GRPC's aio support.
# We need to take the UnaryUnaryCall we receive and return one that remaps the exception.
# It doesn't have any functions to compose operations together, so our only option is to wrap it.
# If the interceptor directly throws an exception other than AioRpcError it breaks GRPC
class CadenceErrorUnaryUnaryCall(UnaryUnaryCall[RequestType, ResponseType]):

    def __init__(self, wrapped: UnaryUnaryCall[RequestType, ResponseType]):
        super().__init__()
        self._wrapped = wrapped

    def __await__(self) -> Generator[Any, None, ResponseType]:
        try:
            response = yield from self._wrapped.__await__() # type: ResponseType
            return response
        except AioRpcError as e:
            raise map_error(e)

    async def initial_metadata(self) -> Metadata:
        return await self._wrapped.initial_metadata()

    async def trailing_metadata(self) -> Metadata:
        return await self._wrapped.trailing_metadata()

    async def code(self) -> grpc.StatusCode:
        return await self._wrapped.code()

    async def details(self) -> str:
        return await self._wrapped.details()  # type: ignore

    async def wait_for_connection(self) -> None:
        await self._wrapped.wait_for_connection()

    def cancelled(self) -> bool:
        return self._wrapped.cancelled() # type: ignore

    def done(self) -> bool:
        return self._wrapped.done() # type: ignore

    def time_remaining(self) -> Optional[float]:
        return self._wrapped.time_remaining() # type: ignore

    def cancel(self) -> bool:
        return self._wrapped.cancel() # type: ignore

    def add_done_callback(self, callback: DoneCallbackType) -> None:
        self._wrapped.add_done_callback(callback)


class CadenceErrorInterceptor(UnaryUnaryClientInterceptor):

    async def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, Any], Any],
        client_call_details: ClientCallDetails,
        request: Any
    ) -> Any:
        rpc_call = await continuation(client_call_details, request)
        return CadenceErrorUnaryUnaryCall(rpc_call)




def map_error(e: AioRpcError) -> error.CadenceError:
    status: Status | None = from_call(e)
    if not status or not status.details:
        return error.CadenceError(e.details(), e.code())

    details = status.details[0]
    if details.Is(error_pb2.WorkflowExecutionAlreadyStartedError.DESCRIPTOR):
        already_started = error_pb2.WorkflowExecutionAlreadyStartedError()
        details.Unpack(already_started)
        return error.WorkflowExecutionAlreadyStartedError(e.details(), e.code(), already_started.start_request_id, already_started.run_id)
    elif details.Is(error_pb2.EntityNotExistsError.DESCRIPTOR):
        not_exists = error_pb2.EntityNotExistsError()
        details.Unpack(not_exists)
        return error.EntityNotExistsError(e.details(), e.code(), not_exists.current_cluster, not_exists.active_cluster, list(not_exists.active_clusters))
    elif details.Is(error_pb2.WorkflowExecutionAlreadyCompletedError.DESCRIPTOR):
        return error.WorkflowExecutionAlreadyCompletedError(e.details(), e.code())
    elif details.Is(error_pb2.DomainNotActiveError.DESCRIPTOR):
        not_active = error_pb2.DomainNotActiveError()
        details.Unpack(not_active)
        return error.DomainNotActiveError(e.details(), e.code(), not_active.domain, not_active.current_cluster, not_active.active_cluster, list(not_active.active_clusters))
    elif details.Is(error_pb2.ClientVersionNotSupportedError.DESCRIPTOR):
        not_supported = error_pb2.ClientVersionNotSupportedError()
        details.Unpack(not_supported)
        return error.ClientVersionNotSupportedError(e.details(), e.code(), not_supported.feature_version, not_supported.client_impl, not_supported.supported_versions)
    elif details.Is(error_pb2.FeatureNotEnabledError.DESCRIPTOR):
        not_enabled = error_pb2.FeatureNotEnabledError()
        details.Unpack(not_enabled)
        return error.FeatureNotEnabledError(e.details(), e.code(), not_enabled.feature_flag)
    elif details.Is(error_pb2.CancellationAlreadyRequestedError.DESCRIPTOR):
        return error.CancellationAlreadyRequestedError(e.details(), e.code())
    elif details.Is(error_pb2.DomainAlreadyExistsError.DESCRIPTOR):
        return error.DomainAlreadyExistsError(e.details(), e.code())
    elif details.Is(error_pb2.LimitExceededError.DESCRIPTOR):
        return error.LimitExceededError(e.details(), e.code())
    elif details.Is(error_pb2.QueryFailedError.DESCRIPTOR):
        return error.QueryFailedError(e.details(), e.code())
    elif details.Is(error_pb2.ServiceBusyError.DESCRIPTOR):
        service_busy = error_pb2.ServiceBusyError()
        details.Unpack(service_busy)
        return error.ServiceBusyError(e.details(), e.code(), service_busy.reason)
    else:
        return error.CadenceError(e.details(), e.code())

