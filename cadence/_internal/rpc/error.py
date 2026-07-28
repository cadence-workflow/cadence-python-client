from collections.abc import Callable, Generator
from typing import Any, TypeVar, cast

import grpc
from google.rpc.status_pb2 import Status
from grpc.aio import (
    AioRpcError,
    ClientCallDetails,
    UnaryUnaryClientInterceptor,
)
from grpc_status.rpc_status import from_call

from cadence import error
from cadence._internal.rpc.call import UnaryUnaryCallWrapper
from cadence.api.v1 import error_pb2

RequestType = TypeVar("RequestType")
ResponseType = TypeVar("ResponseType")


# A UnaryUnaryCall is an awaitable type returned by GRPC's aio support.
# We need to take the UnaryUnaryCall we receive and return one that remaps the exception.
# It doesn't have any functions to compose operations together, so our only option is to wrap it.
# If the interceptor directly throws an exception other than AioRpcError it breaks GRPC
class CadenceErrorUnaryUnaryCall(UnaryUnaryCallWrapper[RequestType, ResponseType]):
    def __await__(self) -> Generator[Any, None, ResponseType]:
        try:
            response = yield from self._wrapped.__await__()  # type: ResponseType
            return response
        except AioRpcError as e:
            raise map_error(e)


class CadenceErrorInterceptor(UnaryUnaryClientInterceptor):
    async def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, Any], Any],
        client_call_details: ClientCallDetails,
        request: Any,
    ) -> Any:
        rpc_call = await continuation(client_call_details, request)
        return CadenceErrorUnaryUnaryCall(rpc_call)


def map_error(e: AioRpcError) -> error.CadenceRpcError:
    # AioRpcError implements the grpc.Call interface but doesn't inherit from it in the type stubs
    status: Status | None = from_call(cast(grpc.Call, e))
    message = e.details() or ""
    if not status or not status.details:
        return error.CadenceRpcError(message, e.code())

    details = status.details[0]
    if details.Is(error_pb2.WorkflowExecutionAlreadyStartedError.DESCRIPTOR):
        already_started = error_pb2.WorkflowExecutionAlreadyStartedError()
        details.Unpack(already_started)
        return error.WorkflowExecutionAlreadyStartedError(
            message,
            e.code(),
            already_started.start_request_id,
            already_started.run_id,
        )
    elif details.Is(error_pb2.EntityNotExistsError.DESCRIPTOR):
        not_exists = error_pb2.EntityNotExistsError()
        details.Unpack(not_exists)
        return error.EntityNotExistsError(
            message,
            e.code(),
            not_exists.current_cluster,
            not_exists.active_cluster,
            list(not_exists.active_clusters),
        )
    elif details.Is(error_pb2.WorkflowExecutionAlreadyCompletedError.DESCRIPTOR):
        return error.WorkflowExecutionAlreadyCompletedError(message, e.code())
    elif details.Is(error_pb2.DomainNotActiveError.DESCRIPTOR):
        not_active = error_pb2.DomainNotActiveError()
        details.Unpack(not_active)
        return error.DomainNotActiveError(
            message,
            e.code(),
            not_active.domain,
            not_active.current_cluster,
            not_active.active_cluster,
            list(not_active.active_clusters),
        )
    elif details.Is(error_pb2.ClientVersionNotSupportedError.DESCRIPTOR):
        not_supported = error_pb2.ClientVersionNotSupportedError()
        details.Unpack(not_supported)
        return error.ClientVersionNotSupportedError(
            message,
            e.code(),
            not_supported.feature_version,
            not_supported.client_impl,
            not_supported.supported_versions,
        )
    elif details.Is(error_pb2.FeatureNotEnabledError.DESCRIPTOR):
        not_enabled = error_pb2.FeatureNotEnabledError()
        details.Unpack(not_enabled)
        return error.FeatureNotEnabledError(message, e.code(), not_enabled.feature_flag)
    elif details.Is(error_pb2.CancellationAlreadyRequestedError.DESCRIPTOR):
        return error.CancellationAlreadyRequestedError(message, e.code())
    elif details.Is(error_pb2.DomainAlreadyExistsError.DESCRIPTOR):
        return error.DomainAlreadyExistsError(message, e.code())
    elif details.Is(error_pb2.LimitExceededError.DESCRIPTOR):
        return error.LimitExceededError(message, e.code())
    elif details.Is(error_pb2.QueryFailedError.DESCRIPTOR):
        return error.QueryFailedError(message, e.code())
    elif details.Is(error_pb2.ServiceBusyError.DESCRIPTOR):
        service_busy = error_pb2.ServiceBusyError()
        details.Unpack(service_busy)
        return error.ServiceBusyError(message, e.code(), service_busy.reason)
    else:
        return error.CadenceRpcError(message, e.code())
