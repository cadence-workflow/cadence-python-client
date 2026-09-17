import inspect
from datetime import timedelta
from typing import Any, Callable

from grpc.aio import ClientCallDetails, Metadata, UnaryUnaryClientInterceptor

from cadence.auth import CADENCE_AUTHORIZATION_HEADER, AuthorizationProvider


class AuthorizationInterceptor(UnaryUnaryClientInterceptor):
    """gRPC ClientInterceptor that injects the authorization token header."""

    def __init__(self, provider: AuthorizationProvider) -> None:
        self._provider = provider

    async def _resolve_token(self) -> str | None:
        if self._provider is None:
            return None

        if hasattr(self._provider, "get_auth_token"):
            raw_token = self._provider.get_auth_token()
        elif callable(self._provider):
            raw_token = self._provider()
        else:
            raw_token = self._provider

        if inspect.isawaitable(raw_token):
            raw_token = await raw_token

        if raw_token is None:
            return None

        if isinstance(raw_token, bytes):
            return raw_token.decode("utf-8")
        return str(raw_token)

    async def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, Any], Any],
        client_call_details: ClientCallDetails,
        request: Any,
    ) -> Any:
        token_str = await self._resolve_token()
        if token_str:
            client_call_details = self._inject_auth_header(
                client_call_details, token_str
            )
        return await continuation(client_call_details, request)

    def _inject_auth_header(
        self, client_call_details: ClientCallDetails, token: str
    ) -> ClientCallDetails:
        auth_metadata = Metadata((CADENCE_AUTHORIZATION_HEADER, token))
        metadata = client_call_details.metadata
        if metadata is None:
            metadata = auth_metadata
        else:
            metadata += auth_metadata

        return ClientCallDetails(
            method=client_call_details.method,
            timeout=client_call_details.timeout
            or timedelta(seconds=60).total_seconds(),
            metadata=metadata,
            credentials=client_call_details.credentials,
            wait_for_ready=client_call_details.wait_for_ready,
        )
