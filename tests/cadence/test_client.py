import uuid
from datetime import timedelta

import grpc
import grpc.aio
import pytest
from opentelemetry.instrumentation.grpc import GrpcAioInstrumentorClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from cadence.api.v1.service_workflow_pb2 import (
    StartWorkflowExecutionRequest,
    StartWorkflowExecutionResponse,
    SignalWorkflowExecutionRequest,
    SignalWorkflowExecutionResponse,
)
from cadence.api.v1.service_workflow_pb2_grpc import (
    WorkflowAPIServicer,
    add_WorkflowAPIServicer_to_server,
)
from cadence.client import Client


class _FakeWorkflowServicer(WorkflowAPIServicer):
    """Minimal servicer that returns canned responses for testing."""

    async def StartWorkflowExecution(
        self,
        request: StartWorkflowExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> StartWorkflowExecutionResponse:
        return StartWorkflowExecutionResponse(run_id=str(uuid.uuid4()))

    async def SignalWorkflowExecution(
        self,
        request: SignalWorkflowExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> SignalWorkflowExecutionResponse:
        return SignalWorkflowExecutionResponse()


@pytest.fixture()
def otel_setup():
    """Set up OTel TracerProvider with an in-memory exporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    instrumentor = GrpcAioInstrumentorClient()
    instrumentor.instrument(tracer_provider=provider)

    yield exporter

    instrumentor.uninstrument()
    provider.shutdown()


@pytest.fixture()
async def cadence_server():
    """Start a gRPC aio server with the fake WorkflowAPI servicer."""
    server = grpc.aio.server()
    add_WorkflowAPIServicer_to_server(_FakeWorkflowServicer(), server)
    port = server.add_insecure_port("localhost:0")
    await server.start()
    yield port
    await server.stop(grace=0)


class TestOpenTelemetryGrpcCompatibility:
    """Verify that the client works correctly with opentelemetry-instrumentation-grpc."""

    @pytest.mark.asyncio
    async def test_start_workflow_produces_otel_span(
        self, otel_setup: InMemorySpanExporter, cadence_server: int
    ):
        """An instrumented client produces an OTel span for StartWorkflowExecution."""
        client = Client(domain="test-domain", target=f"localhost:{cadence_server}")
        try:
            await client.start_workflow(
                "MyWorkflow",
                task_list="test-tl",
                execution_start_to_close_timeout=timedelta(minutes=10),
            )
        finally:
            await client.close()

        spans = otel_setup.get_finished_spans()
        rpc_names = [s.name for s in spans]
        assert any("StartWorkflowExecution" in name for name in rpc_names), (
            f"Expected a span for StartWorkflowExecution, got: {rpc_names}"
        )

    @pytest.mark.asyncio
    async def test_signal_workflow_produces_otel_span(
        self, otel_setup: InMemorySpanExporter, cadence_server: int
    ):
        """An instrumented client produces an OTel span for SignalWorkflowExecution."""
        client = Client(domain="test-domain", target=f"localhost:{cadence_server}")
        try:
            await client.signal_workflow("wf-id", "run-id", "my-signal")
        finally:
            await client.close()

        spans = otel_setup.get_finished_spans()
        rpc_names = [s.name for s in spans]
        assert any("SignalWorkflowExecution" in name for name in rpc_names), (
            f"Expected a span for SignalWorkflowExecution, got: {rpc_names}"
        )

    @pytest.mark.asyncio
    async def test_span_has_grpc_attributes(
        self, otel_setup: InMemorySpanExporter, cadence_server: int
    ):
        """OTel spans carry standard gRPC semantic-convention attributes."""
        client = Client(domain="test-domain", target=f"localhost:{cadence_server}")
        try:
            await client.start_workflow(
                "MyWorkflow",
                task_list="test-tl",
                execution_start_to_close_timeout=timedelta(minutes=10),
            )
        finally:
            await client.close()

        spans = otel_setup.get_finished_spans()
        start_spans = [s for s in spans if "StartWorkflowExecution" in s.name]
        assert start_spans, "No StartWorkflowExecution span found"

        attrs = dict(start_spans[0].attributes or {})
        assert attrs.get("rpc.system") == "grpc"
        assert attrs.get("rpc.service") == "uber.cadence.api.v1.WorkflowAPI"
        assert attrs.get("rpc.method") == "StartWorkflowExecution"

    @pytest.mark.asyncio
    async def test_client_interceptors_still_work_under_otel(
        self, otel_setup: InMemorySpanExporter
    ):
        """YARPC metadata interceptor still injects headers when OTel is active."""
        received_metadata: dict[str, str] = {}

        class _MetadataCapturingServicer(WorkflowAPIServicer):
            async def StartWorkflowExecution(self, request, context):
                for key, value in context.invocation_metadata():
                    received_metadata[key] = value
                return StartWorkflowExecutionResponse(run_id=str(uuid.uuid4()))

        server = grpc.aio.server()
        add_WorkflowAPIServicer_to_server(_MetadataCapturingServicer(), server)
        port = server.add_insecure_port("localhost:0")
        await server.start()

        try:
            client = Client(domain="test-domain", target=f"localhost:{port}")
            try:
                await client.start_workflow(
                    "MyWorkflow",
                    task_list="test-tl",
                    execution_start_to_close_timeout=timedelta(minutes=10),
                )
            finally:
                await client.close()
        finally:
            await server.stop(grace=0)

        assert received_metadata.get("rpc-service") == "cadence-frontend"
        assert received_metadata.get("rpc-caller") == "cadence-client"
        assert received_metadata.get("rpc-encoding") == "proto"

    @pytest.mark.asyncio
    async def test_client_works_without_otel_instrumentation(self, cadence_server: int):
        """Client still works normally when OTel is NOT active (no regressions)."""
        client = Client(domain="test-domain", target=f"localhost:{cadence_server}")
        try:
            execution = await client.start_workflow(
                "MyWorkflow",
                task_list="test-tl",
                execution_start_to_close_timeout=timedelta(minutes=10),
            )
            assert execution.workflow_id
            assert execution.run_id
        finally:
            await client.close()
