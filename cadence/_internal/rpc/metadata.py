import collections

from grpc.aio import Metadata
from grpc.aio import UnaryUnaryClientInterceptor, ClientCallDetails


class _ClientCallDetails(
    collections.namedtuple(
        "_ClientCallDetails", ("method", "timeout", "metadata", "credentials", "wait_for_ready")
    ),
    ClientCallDetails,
):
    pass

class MetadataInterceptor(UnaryUnaryClientInterceptor):
    def __init__(self, metadata: Metadata):
        self._metadata = metadata

    async def intercept_unary_unary(self, continuation, client_call_details: ClientCallDetails, request):
        return await continuation(self._replace_details(client_call_details), request)


    def _replace_details(self, client_call_details: ClientCallDetails) -> ClientCallDetails:
        metadata = client_call_details.metadata
        if metadata is None:
            metadata = self._metadata
        else:
            metadata += self._metadata

        return _ClientCallDetails(
            method=client_call_details.method,
            timeout=client_call_details.timeout,
            metadata=metadata,
            credentials=client_call_details.credentials,
            wait_for_ready=client_call_details.wait_for_ready,
        )
