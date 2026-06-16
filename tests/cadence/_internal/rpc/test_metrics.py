from concurrent import futures
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.protobuf import any_pb2
from google.rpc import code_pb2, status_pb2
from grpc import server
from grpc.aio import insecure_channel
from grpc_status.rpc_status import to_status

from cadence._internal.rpc.error import CadenceErrorInterceptor
from cadence._internal.rpc.metrics import MetricsInterceptor, _extract_method_name
from cadence.api.v1 import error_pb2, service_workflow_pb2_grpc
from cadence.api.v1.service_workflow_pb2 import (
    DescribeWorkflowExecutionRequest,
    DescribeWorkflowExecutionResponse,
)
from cadence.metrics.constants import (
    CADENCE_ERROR,
    CADENCE_LATENCY,
    CADENCE_METRICS_PREFIX,
    CADENCE_REQUEST,
)


class _FakeWorkflowService(service_workflow_pb2_grpc.WorkflowAPIServicer):
    def DescribeWorkflowExecution(self, request, context):
        if request.domain == "success":
            return DescribeWorkflowExecutionResponse()
        detail = any_pb2.Any()
        detail.Pack(error_pb2.FeatureNotEnabledError(feature_flag="flag"))
        context.abort_with_status(
            to_status(
                status_pb2.Status(
                    code=code_pb2.PERMISSION_DENIED, message="denied", details=[detail]
                )
            )
        )


@pytest.fixture(scope="module")
def fake_wf_service():
    svc = _FakeWorkflowService()
    sync_server = server(futures.ThreadPoolExecutor(max_workers=1))
    service_workflow_pb2_grpc.add_WorkflowAPIServicer_to_server(svc, sync_server)
    port = sync_server.add_insecure_port("[::]:0")
    sync_server.start()
    yield svc, port
    sync_server.stop(grace=None)


def _make_mock_emitter():
    emitter = MagicMock()
    emitter.counter = MagicMock()
    emitter.histogram = MagicMock()
    return emitter


def _operation_metric(operation: str, metric: str) -> str:
    return f"{CADENCE_METRICS_PREFIX}{operation}.{metric}"


@pytest.mark.asyncio
async def test_metrics_emitted_on_success(fake_wf_service):
    _, port = fake_wf_service
    emitter = _make_mock_emitter()
    interceptors: list[Any] = [MetricsInterceptor(emitter), CadenceErrorInterceptor()]
    async with insecure_channel(f"[::]:{port}", interceptors=interceptors) as channel:
        stub = service_workflow_pb2_grpc.WorkflowAPIStub(channel)
        await stub.DescribeWorkflowExecution(
            DescribeWorkflowExecutionRequest(domain="success"), timeout=10
        )

    operation = "DescribeWorkflowExecution"
    emitter.with_tags.assert_not_called()
    emitter.counter.assert_called_once_with(_operation_metric(operation, CADENCE_REQUEST))
    emitter.histogram.assert_called_once()
    histogram_call = emitter.histogram.call_args
    assert histogram_call[0][0] == _operation_metric(operation, CADENCE_LATENCY)
    assert histogram_call[0][1] >= timedelta(0)


@pytest.mark.asyncio
async def test_metrics_emitted_on_error(fake_wf_service):
    _, port = fake_wf_service
    emitter = _make_mock_emitter()
    interceptors: list[Any] = [MetricsInterceptor(emitter), CadenceErrorInterceptor()]
    async with insecure_channel(f"[::]:{port}", interceptors=interceptors) as channel:
        stub = service_workflow_pb2_grpc.WorkflowAPIStub(channel)
        with pytest.raises(Exception):
            await stub.DescribeWorkflowExecution(
                DescribeWorkflowExecutionRequest(domain="fail"), timeout=10
            )

    operation = "DescribeWorkflowExecution"
    emitter.with_tags.assert_not_called()
    assert emitter.counter.call_count == 2
    emitter.counter.assert_any_call(_operation_metric(operation, CADENCE_REQUEST))
    emitter.counter.assert_any_call(_operation_metric(operation, CADENCE_ERROR))
    emitter.histogram.assert_called_once()
    assert emitter.histogram.call_args[0][0] == _operation_metric(
        operation, CADENCE_LATENCY
    )


@pytest.mark.asyncio
async def test_metrics_emitted_when_continuation_raises():
    emitter = _make_mock_emitter()
    interceptor = MetricsInterceptor(emitter)
    details = MagicMock(method=b"/cadence.WorkflowAPI/StartWorkflowExecution")

    async def continuation(_details, _request):
        raise RuntimeError("channel setup failed")

    with pytest.raises(RuntimeError, match="channel setup failed"):
        await interceptor.intercept_unary_unary(continuation, details, object())

    operation = "StartWorkflowExecution"
    emitter.with_tags.assert_not_called()
    emitter.counter.assert_any_call(_operation_metric(operation, CADENCE_REQUEST))
    emitter.counter.assert_any_call(_operation_metric(operation, CADENCE_ERROR))
    emitter.histogram.assert_called_once()


@pytest.mark.parametrize(
    "method,expected",
    [
        (b"/uber.cadence.api.v1.WorkerAPI/PollForDecisionTask", "PollForDecisionTask"),
        (b"/uber.cadence.api.v1.WorkflowAPI/StartWorkflowExecution", "StartWorkflowExecution"),
        ("SimpleMethod", "SimpleMethod"),
        (b"NoSlash", "NoSlash"),
    ],
)
def test_extract_method_name(method, expected):
    assert _extract_method_name(method) == expected
