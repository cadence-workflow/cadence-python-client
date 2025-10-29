import asyncio
from dataclasses import dataclass
from typing import Callable, Any

from grpc import StatusCode
from grpc.aio import UnaryUnaryClientInterceptor, ClientCallDetails

from cadence.error import CadenceError, EntityNotExistsError

RETRYABLE_CODES = {
    StatusCode.INTERNAL,
    StatusCode.RESOURCE_EXHAUSTED,
    StatusCode.ABORTED,
    StatusCode.UNAVAILABLE,
}


# No expiration interval, use the GRPC timeout value instead
@dataclass
class ExponentialRetryPolicy:
    initial_interval: float
    backoff_coefficient: float
    max_interval: float
    max_attempts: float

    def next_delay(
        self, attempts: int, elapsed: float, expiration: float
    ) -> float | None:
        if elapsed >= expiration:
            return None
        if self.max_attempts != 0 and attempts >= self.max_attempts:
            return None

        backoff = min(
            self.initial_interval * pow(self.backoff_coefficient, attempts - 1),
            self.max_interval,
        )
        if (elapsed + backoff) >= expiration:
            return None

        return backoff


DEFAULT_RETRY_POLICY = ExponentialRetryPolicy(
    initial_interval=0.02, backoff_coefficient=1.2, max_interval=6, max_attempts=0
)
GET_WORKFLOW_HISTORY = b"/uber.cadence.api.v1.WorkflowAPI/GetWorkflowExecutionHistory"


class RetryInterceptor(UnaryUnaryClientInterceptor):
    def __init__(self, retry_policy: ExponentialRetryPolicy = DEFAULT_RETRY_POLICY):
        super().__init__()
        self._retry_policy = retry_policy

    async def intercept_unary_unary(
        self,
        continuation: Callable[[ClientCallDetails, Any], Any],
        client_call_details: ClientCallDetails,
        request: Any,
    ) -> Any:
        loop = asyncio.get_running_loop()
        expiration_interval = client_call_details.timeout
        start_time = loop.time()
        deadline = start_time + expiration_interval

        attempts = 0
        while True:
            remaining = deadline - loop.time()
            # Namedtuple methods start with an underscore to avoid conflicts and aren't actually private
            # noinspection PyProtectedMember
            call_details = client_call_details._replace(timeout=remaining)
            rpc_call = await continuation(call_details, request)
            try:
                # Return the result directly if success. GRPC will wrap it back into a UnaryUnaryCall
                return await rpc_call
            except CadenceError as e:
                err = e

            attempts += 1
            elapsed = loop.time() - start_time
            backoff = self._retry_policy.next_delay(
                attempts, elapsed, expiration_interval
            )
            if not is_retryable(err, client_call_details) or backoff is None:
                break

            await asyncio.sleep(backoff)

        # On policy expiration, return the most recent UnaryUnaryCall. It has the error we want
        return rpc_call


def is_retryable(err: CadenceError, call_details: ClientCallDetails) -> bool:
    # Handle requests to the passive side, matching the Go and Java Clients
    if call_details.method == GET_WORKFLOW_HISTORY and isinstance(
        err, EntityNotExistsError
    ):
        return (
            err.active_cluster is not None
            and err.current_cluster is not None
            and err.active_cluster != err.current_cluster
        )

    return err.code in RETRYABLE_CODES
