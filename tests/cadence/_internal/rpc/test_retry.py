from concurrent import futures
from typing import Tuple, Type

import pytest
from google.protobuf import any_pb2
from google.rpc import status_pb2, code_pb2
from grpc import server
from grpc.aio import insecure_channel
from grpc_status.rpc_status import to_status

from cadence._internal.rpc.error import CadenceErrorInterceptor
from cadence.api.v1 import error_pb2, service_workflow_pb2_grpc

from cadence._internal.rpc.retry import ExponentialRetryPolicy, RetryInterceptor
from cadence.api.v1.service_workflow_pb2 import DescribeWorkflowExecutionResponse, \
    DescribeWorkflowExecutionRequest, GetWorkflowExecutionHistoryRequest
from cadence.error import CadenceError, FeatureNotEnabledError, EntityNotExistsError

simple_policy = ExponentialRetryPolicy(initial_interval=1, backoff_coefficient=2, max_interval=10, max_attempts=6)

@pytest.mark.parametrize(
    "policy,params,expected",
    [
        pytest.param(
            simple_policy, (1, 0.0, 100.0), 1, id="happy path"
        ),
        pytest.param(
            simple_policy, (2, 0.0, 100.0), 2, id="second attempt"
        ),
        pytest.param(
            simple_policy, (3, 0.0, 100.0), 4, id="third attempt"
        ),
        pytest.param(
            simple_policy, (5, 0.0, 100.0), 10, id="capped by max_interval"
        ),
        pytest.param(
            simple_policy, (6, 0.0, 100.0), None, id="out of attempts"
        ),
        pytest.param(
            simple_policy, (1, 100.0, 100.0), None, id="timeout"
        ),
        pytest.param(
            simple_policy, (1, 99.0, 100.0), None, id="backoff causes timeout"
        ),
        pytest.param(
            ExponentialRetryPolicy(initial_interval=1, backoff_coefficient=1, max_interval=10, max_attempts=0), (100, 0.0, 100.0), 1, id="unlimited retries"
        ),
    ]
)
def test_next_delay(policy: ExponentialRetryPolicy, params: Tuple[int, float, float], expected: float | None):
    assert policy.next_delay(*params) == expected


class FakeService(service_workflow_pb2_grpc.WorkflowAPIServicer):
    def __init__(self) -> None:
        super().__init__()
        self.port = None
        self.counter = 0

    # Retryable only because it's GetWorkflowExecutionHistory
    def GetWorkflowExecutionHistory(self, request: GetWorkflowExecutionHistoryRequest, context):
        self.counter += 1

        detail = any_pb2.Any()
        detail.Pack(error_pb2.EntityNotExistsError(current_cluster=request.domain, active_cluster="active"))
        status_proto = status_pb2.Status(
            code=code_pb2.NOT_FOUND,
            message="message",
            details=[detail],
        )
        context.abort_with_status(to_status(status_proto))
            # Unreachable


    # Not retryable
    def DescribeWorkflowExecution(self, request: DescribeWorkflowExecutionRequest, context):
        self.counter += 1

        if request.domain == "success":
            return DescribeWorkflowExecutionResponse()
        elif request.domain == "retryable":
            code = code_pb2.RESOURCE_EXHAUSTED
        elif request.domain == "maybe later":
            if self.counter >= 3:
                return DescribeWorkflowExecutionResponse()

            code = code_pb2.RESOURCE_EXHAUSTED
        else:
            code = code_pb2.PERMISSION_DENIED

        detail = any_pb2.Any()
        detail.Pack(error_pb2.FeatureNotEnabledError(feature_flag="the flag"))
        status_proto = status_pb2.Status(
            code=code,
            message="message",
            details=[detail],
        )
        context.abort_with_status(to_status(status_proto))
        # Unreachable


@pytest.fixture(scope="module")
def fake_service():
    fake = FakeService()
    sync_server = server(futures.ThreadPoolExecutor(max_workers=1))
    service_workflow_pb2_grpc.add_WorkflowAPIServicer_to_server(fake, sync_server)
    fake.port = sync_server.add_insecure_port("[::]:0")
    sync_server.start()
    yield fake
    sync_server.stop(grace=None)

TEST_POLICY = ExponentialRetryPolicy(initial_interval=0, backoff_coefficient=0, max_interval=10, max_attempts=10)

@pytest.mark.usefixtures("fake_service")
@pytest.mark.parametrize(
    "case,expected_calls,expected_err",
    [
        pytest.param(
            "success", 1, None, id="happy path"
        ),
        pytest.param(
            "maybe later", 3, None, id="retries then success"
        ),
        pytest.param(
            "not retryable", 1, FeatureNotEnabledError, id="not retryable"
        ),
        pytest.param(
            "retryable", TEST_POLICY.max_attempts, FeatureNotEnabledError, id="retries exhausted"
        ),

    ]
)
@pytest.mark.asyncio
async def test_retryable_error(fake_service, case: str, expected_calls: int, expected_err: Type[CadenceError]):
    fake_service.counter = 0
    async with insecure_channel(f"[::]:{fake_service.port}", interceptors=[RetryInterceptor(TEST_POLICY), CadenceErrorInterceptor()]) as channel:
        stub = service_workflow_pb2_grpc.WorkflowAPIStub(channel)
        if expected_err:
            with pytest.raises(expected_err):
                await stub.DescribeWorkflowExecution(DescribeWorkflowExecutionRequest(domain=case), timeout=10)
        else:
            await stub.DescribeWorkflowExecution(DescribeWorkflowExecutionRequest(domain=case), timeout=10)

        assert fake_service.counter == expected_calls

@pytest.mark.usefixtures("fake_service")
@pytest.mark.parametrize(
    "case,expected_calls",
    [
        pytest.param(
            "active", 1, id="not retryable"
        ),
        pytest.param(
            "not active", TEST_POLICY.max_attempts, id="retries exhausted"
        ),

    ]
)
@pytest.mark.asyncio
async def test_workflow_history(fake_service, case: str, expected_calls: int):
    fake_service.counter = 0
    async with insecure_channel(f"[::]:{fake_service.port}", interceptors=[RetryInterceptor(TEST_POLICY), CadenceErrorInterceptor()]) as channel:
        stub = service_workflow_pb2_grpc.WorkflowAPIStub(channel)
        with pytest.raises(EntityNotExistsError):
            await stub.GetWorkflowExecutionHistory(GetWorkflowExecutionHistoryRequest(domain=case), timeout=10)

        assert fake_service.counter == expected_calls