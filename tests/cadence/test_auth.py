import uuid
from datetime import timedelta

import grpc
import grpc.aio
import pytest

from cadence.api.v1.service_workflow_pb2 import (
    StartWorkflowExecutionRequest,
    StartWorkflowExecutionResponse,
)
from cadence.api.v1.service_workflow_pb2_grpc import (
    WorkflowAPIServicer,
    add_WorkflowAPIServicer_to_server,
)
from cadence.auth import (
    CADENCE_AUTHORIZATION_HEADER,
    AuthorizationProvider,
    CallableAuthorizationProvider,
    StaticAuthorizationProvider,
)
from cadence.client import Client


class _MetadataCapturingServicer(WorkflowAPIServicer):
    """Workflow servicer that captures all gRPC invocation metadata."""

    def __init__(self) -> None:
        self.received_metadata: dict[str, str] = {}

    async def StartWorkflowExecution(
        self,
        request: StartWorkflowExecutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> StartWorkflowExecutionResponse:
        for key, value in context.invocation_metadata():
            self.received_metadata[key] = value
        return StartWorkflowExecutionResponse(run_id=str(uuid.uuid4()))


@pytest.fixture()
async def auth_test_server():
    """Start an in-process gRPC aio server capturing request metadata."""
    servicer = _MetadataCapturingServicer()
    server = grpc.aio.server()
    add_WorkflowAPIServicer_to_server(servicer, server)
    port = server.add_insecure_port("localhost:0")
    await server.start()
    yield port, servicer
    await server.stop(grace=0)


class TestAuthorizationProviders:
    """Test unit behavior of AuthorizationProvider implementations."""

    def test_static_provider_str(self):
        provider = StaticAuthorizationProvider("Bearer test-token-123")
        assert provider.get_auth_token() == "Bearer test-token-123"

    def test_static_provider_bytes(self):
        provider = StaticAuthorizationProvider(b"Bearer byte-token-456")
        assert provider.get_auth_token() == b"Bearer byte-token-456"

    def test_static_provider_empty_raises(self):
        with pytest.raises(ValueError, match="Token must not be empty"):
            StaticAuthorizationProvider("")

    def test_callable_provider_sync(self):
        counter = 0

        def get_token():
            nonlocal counter
            counter += 1
            return f"Bearer token-{counter}"

        provider = CallableAuthorizationProvider(get_token)
        assert provider.get_auth_token() == "Bearer token-1"
        assert provider.get_auth_token() == "Bearer token-2"

    @pytest.mark.asyncio
    async def test_callable_provider_async(self):
        async def async_get_token():
            return "Bearer async-token"

        provider = CallableAuthorizationProvider(async_get_token)
        result = provider.get_auth_token()
        token = await result
        assert token == "Bearer async-token"

    def test_callable_provider_invalid_raises(self):
        with pytest.raises(TypeError, match="must be callable"):
            CallableAuthorizationProvider("not-callable")  # type: ignore


class CustomOAuthProvider(AuthorizationProvider):
    """Example custom OAuth token provider."""

    def __init__(self, prefix: str = "custom") -> None:
        self.prefix = prefix
        self.calls = 0

    def get_auth_token(self) -> str:
        self.calls += 1
        return f"OAuth-{self.prefix}-{self.calls}"


class TestClientAuthorizationIntegration:
    """End-to-end integration tests with Client and gRPC servicer."""

    @pytest.mark.asyncio
    async def test_client_sends_static_string_auth_header(self, auth_test_server):
        port, servicer = auth_test_server
        token = "Bearer test-static-jwt-token"
        provider = StaticAuthorizationProvider(token)

        client = Client(
            domain="test-domain",
            target=f"localhost:{port}",
            authorization_provider=provider,
        )
        assert client.authorization_provider is provider

        try:
            await client.start_workflow(
                "MyWorkflow",
                task_list="test-tl",
                execution_start_to_close_timeout=timedelta(minutes=5),
            )
        finally:
            await client.close()

        assert servicer.received_metadata.get(CADENCE_AUTHORIZATION_HEADER) == token
        assert servicer.received_metadata.get("rpc-service") == "cadence-frontend"

    @pytest.mark.asyncio
    async def test_client_sends_bytes_auth_header(self, auth_test_server):
        port, servicer = auth_test_server
        token_bytes = b"Bearer binary-encoded-token-xyz"
        provider = StaticAuthorizationProvider(token_bytes)

        client = Client(
            domain="test-domain",
            target=f"localhost:{port}",
            authorization_provider=provider,
        )

        try:
            await client.start_workflow(
                "MyWorkflow",
                task_list="test-tl",
                execution_start_to_close_timeout=timedelta(minutes=5),
            )
        finally:
            await client.close()

        assert (
            servicer.received_metadata.get(CADENCE_AUTHORIZATION_HEADER)
            == "Bearer binary-encoded-token-xyz"
        )

    @pytest.mark.asyncio
    async def test_client_sends_async_auth_token(self, auth_test_server):
        port, servicer = auth_test_server

        async def async_token_generator():
            return "Bearer async-oauth-token-777"

        provider = CallableAuthorizationProvider(async_token_generator)
        client = Client(
            domain="test-domain",
            target=f"localhost:{port}",
            authorization_provider=provider,
        )

        try:
            await client.start_workflow(
                "MyWorkflow",
                task_list="test-tl",
                execution_start_to_close_timeout=timedelta(minutes=5),
            )
        finally:
            await client.close()

        assert (
            servicer.received_metadata.get(CADENCE_AUTHORIZATION_HEADER)
            == "Bearer async-oauth-token-777"
        )

    @pytest.mark.asyncio
    async def test_client_sends_custom_provider_token(self, auth_test_server):
        port, servicer = auth_test_server
        provider = CustomOAuthProvider("production")

        client = Client(
            domain="test-domain",
            target=f"localhost:{port}",
            authorization_provider=provider,
        )

        try:
            await client.start_workflow(
                "MyWorkflow",
                task_list="test-tl",
                execution_start_to_close_timeout=timedelta(minutes=5),
            )
        finally:
            await client.close()

        assert (
            servicer.received_metadata.get(CADENCE_AUTHORIZATION_HEADER)
            == "OAuth-production-1"
        )
        assert provider.calls == 1

    @pytest.mark.asyncio
    async def test_client_without_auth_provider_does_not_send_auth_header(
        self, auth_test_server
    ):
        port, servicer = auth_test_server

        client = Client(
            domain="test-domain",
            target=f"localhost:{port}",
        )
        assert client.authorization_provider is None

        try:
            await client.start_workflow(
                "MyWorkflow",
                task_list="test-tl",
                execution_start_to_close_timeout=timedelta(minutes=5),
            )
        finally:
            await client.close()

        assert CADENCE_AUTHORIZATION_HEADER not in servicer.received_metadata
        assert servicer.received_metadata.get("rpc-service") == "cadence-frontend"

    def test_static_provider_rejects_non_utf8_bytes(self):
        non_utf8_bytes = b"\xff\xfe\xfa\xbc"
        with pytest.raises(ValueError, match="valid UTF-8 encoded string"):
            StaticAuthorizationProvider(non_utf8_bytes)

    @pytest.mark.asyncio
    async def test_callable_provider_rejects_non_utf8_bytes_during_resolution(
        self, auth_test_server
    ):
        port, _ = auth_test_server
        provider = CallableAuthorizationProvider(lambda: b"\xff\xfe\xfa\xbc")

        client = Client(
            domain="test-domain",
            target=f"localhost:{port}",
            authorization_provider=provider,
        )

        try:
            with pytest.raises(ValueError, match="valid UTF-8 encoded string"):
                await client.start_workflow(
                    "MyWorkflow",
                    task_list="test-tl",
                    execution_start_to_close_timeout=timedelta(minutes=5),
                )
        finally:
            await client.close()
