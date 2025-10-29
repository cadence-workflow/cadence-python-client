from typing import Any, Callable

from grpc.aio import Metadata
from grpc.aio import UnaryUnaryClientInterceptor, ClientCallDetails


SERVICE_KEY = "rpc-service"
CALLER_KEY = "rpc-caller"
ENCODING_KEY = "rpc-encoding"
ENCODING_PROTO = "proto"


class YarpcMetadataInterceptor(UnaryUnaryClientInterceptor):
    def __init__(self, service: str, caller: str):
        self._metadata = Metadata(
            (SERVICE_KEY, service),
            (CALLER_KEY, caller),
            (ENCODING_KEY, ENCODING_PROTO),
        )

    async def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, Any], Any],
        client_call_details: ClientCallDetails,
        request: Any,
    ) -> Any:
        return await continuation(self._replace_details(client_call_details), request)

    def _replace_details(
        self, client_call_details: ClientCallDetails
    ) -> ClientCallDetails:
        metadata = client_call_details.metadata
        if metadata is None:
            metadata = self._metadata
        else:
            metadata += self._metadata

        # Namedtuple methods start with an underscore to avoid conflicts and aren't actually private
        # noinspection PyProtectedMember
        return client_call_details._replace(
            metadata=metadata, timeout=client_call_details.timeout or 60.0
        )
