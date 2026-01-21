from concurrent import futures

import pytest
from google.protobuf import any_pb2
from google.rpc import code_pb2, status_pb2  # type: ignore
from grpc import Status, StatusCode, server
from grpc.aio import insecure_channel
from grpc_status.rpc_status import to_status  # type: ignore

from cadence._internal.rpc.error import CadenceErrorInterceptor
from cadence.api.v1 import error_pb2, service_meta_pb2_grpc
from cadence import error
from google.protobuf.message import Message

from cadence.api.v1.service_meta_pb2 import HealthRequest, HealthResponse
from cadence.error import CadenceRpcError


class FakeService(service_meta_pb2_grpc.MetaAPIServicer):
    def __init__(self) -> None:
        super().__init__()
        self.status: Status | None = None
        self.port: int | None = None

    def Health(self, request, context):
        if temp := self.status:
            self.status = None
            context.abort_with_status(temp)
        return HealthResponse(ok=True)


@pytest.fixture(scope="module")
def fake_service():
    fake = FakeService()
    sync_server = server(futures.ThreadPoolExecutor(max_workers=1))
    service_meta_pb2_grpc.add_MetaAPIServicer_to_server(fake, sync_server)
    fake.port = sync_server.add_insecure_port("[::]:0")
    sync_server.start()
    yield fake
    sync_server.stop(grace=None)


@pytest.mark.usefixtures("fake_service")
@pytest.mark.parametrize(
    "err,expected",
    [
        pytest.param(None, None, id="no error"),
        pytest.param(
            error_pb2.WorkflowExecutionAlreadyStartedError(
                start_request_id="start_request", run_id="run_id"
            ),
            error.WorkflowExecutionAlreadyStartedError(
                message="message",
                code=StatusCode.INVALID_ARGUMENT,
                start_request_id="start_request",
                run_id="run_id",
            ),
            id="WorkflowExecutionAlreadyStartedError",
        ),
        pytest.param(
            error_pb2.EntityNotExistsError(
                current_cluster="current_cluster",
                active_cluster="active_cluster",
                active_clusters=["active_clusters"],
            ),
            error.EntityNotExistsError(
                message="message",
                code=StatusCode.INVALID_ARGUMENT,
                current_cluster="current_cluster",
                active_cluster="active_cluster",
                active_clusters=["active_clusters"],
            ),
            id="EntityNotExistsError",
        ),
        pytest.param(
            error_pb2.WorkflowExecutionAlreadyCompletedError(),
            error.WorkflowExecutionAlreadyCompletedError(
                message="message", code=StatusCode.INVALID_ARGUMENT
            ),
            id="WorkflowExecutionAlreadyCompletedError",
        ),
        pytest.param(
            error_pb2.DomainNotActiveError(
                domain="domain",
                current_cluster="current_cluster",
                active_cluster="active_cluster",
                active_clusters=["active_clusters"],
            ),
            error.DomainNotActiveError(
                message="message",
                code=StatusCode.INVALID_ARGUMENT,
                domain="domain",
                current_cluster="current_cluster",
                active_cluster="active_cluster",
                active_clusters=["active_clusters"],
            ),
            id="DomainNotActiveError",
        ),
        pytest.param(
            error_pb2.ClientVersionNotSupportedError(
                feature_version="feature_version",
                client_impl="client_impl",
                supported_versions="supported_versions",
            ),
            error.ClientVersionNotSupportedError(
                message="message",
                code=StatusCode.INVALID_ARGUMENT,
                feature_version="feature_version",
                client_impl="client_impl",
                supported_versions="supported_versions",
            ),
            id="ClientVersionNotSupportedError",
        ),
        pytest.param(
            error_pb2.FeatureNotEnabledError(feature_flag="feature_flag"),
            error.FeatureNotEnabledError(
                message="message",
                code=StatusCode.INVALID_ARGUMENT,
                feature_flag="feature_flag",
            ),
            id="FeatureNotEnabledError",
        ),
        pytest.param(
            error_pb2.CancellationAlreadyRequestedError(),
            error.CancellationAlreadyRequestedError(
                message="message", code=StatusCode.INVALID_ARGUMENT
            ),
            id="CancellationAlreadyRequestedError",
        ),
        pytest.param(
            error_pb2.DomainAlreadyExistsError(),
            error.DomainAlreadyExistsError(
                message="message", code=StatusCode.INVALID_ARGUMENT
            ),
            id="DomainAlreadyExistsError",
        ),
        pytest.param(
            error_pb2.LimitExceededError(),
            error.LimitExceededError(
                message="message", code=StatusCode.INVALID_ARGUMENT
            ),
            id="LimitExceededError",
        ),
        pytest.param(
            error_pb2.QueryFailedError(),
            error.QueryFailedError(message="message", code=StatusCode.INVALID_ARGUMENT),
            id="QueryFailedError",
        ),
        pytest.param(
            error_pb2.ServiceBusyError(reason="reason"),
            error.ServiceBusyError(
                message="message", code=StatusCode.INVALID_ARGUMENT, reason="reason"
            ),
            id="ServiceBusyError",
        ),
        pytest.param(
            to_status(
                status_pb2.Status(
                    code=code_pb2.PERMISSION_DENIED, message="no permission"
                )
            ),
            error.CadenceRpcError(
                message="no permission", code=StatusCode.PERMISSION_DENIED
            ),
            id="unknown error type",
        ),
    ],
)
@pytest.mark.asyncio
async def test_map_error(
    fake_service, err: Message | Status, expected: CadenceRpcError | None
):
    async with insecure_channel(
        f"[::]:{fake_service.port}", interceptors=[CadenceErrorInterceptor()]
    ) as channel:
        stub = service_meta_pb2_grpc.MetaAPIStub(channel)
        if expected is None:
            response = await stub.Health(HealthRequest(), timeout=1)
            assert response == HealthResponse(ok=True)
        else:
            if isinstance(err, Message):
                fake_service.status = details_to_status(err)
            else:
                fake_service.status = err
            with pytest.raises(type(expected)) as exc_info:
                await stub.Health(HealthRequest(), timeout=1)
            assert exc_info.value.args == expected.args


def details_to_status(message: Message) -> Status:
    detail = any_pb2.Any()
    detail.Pack(message)
    status_proto = status_pb2.Status(
        code=code_pb2.INVALID_ARGUMENT,
        message="message",
        details=[detail],
    )
    return to_status(status_proto)
