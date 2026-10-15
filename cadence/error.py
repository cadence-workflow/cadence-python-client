from datetime import timedelta
from typing import TYPE_CHECKING, Any, Self

import grpc
from google.protobuf.internal.enum_type_wrapper import EnumTypeWrapper

from cadence.api.v1 import common_pb2, workflow_pb2
from cadence.api.v1.common_pb2 import Payload

if TYPE_CHECKING:
    from cadence.data_converter import DataConverter


def _enum_name(enum_type: EnumTypeWrapper, value: int, prefix: str) -> str:
    try:
        name: str = enum_type.Name(value)
    except ValueError:
        return str(value)
    return name.removeprefix(prefix)


class CadenceError(Exception):
    """Base class for all errors raised by the Cadence client."""


class ContinueAsNewError(CadenceError):
    def __init__(
        self,
        *args: Any,
        workflow_type: str | None = None,
        task_list: str | None = None,
        execution_start_to_close_timeout: timedelta | None = None,
        task_start_to_close_timeout: timedelta | None = None,
        headers: dict[str, bytes] | None = None,
    ):
        super().__init__("ContinueAsNew")
        self.workflow_args = args
        self.workflow_type = workflow_type
        self.task_list = task_list
        self.execution_start_to_close_timeout = execution_start_to_close_timeout
        self.task_start_to_close_timeout = task_start_to_close_timeout
        self.headers = headers


class FailureError(CadenceError):
    """A durable failure from workflow history, raised into workflow code.

    Every error the SDK raises into workflow code for a failed operation is a
    ``FailureError`` built from a history event, so it's the same on replay.
    :class:`ApplicationError` can also be raised by activity or workflow code;
    the SDK records it in history as the activity's or workflow's outcome.
    """


class _DetailsError(FailureError):
    """A failure whose details are local values or a payload received from Cadence."""

    def __init__(self, message: str, details: tuple[Any, ...]) -> None:
        super().__init__(message)
        self._values = details
        self._payload: Payload | None = None
        self._data_converter: "DataConverter | None" = None

    def has_details(self) -> bool:
        if self._payload is not None:
            return bool(self._payload.data)
        return bool(self._values)

    def details(self, *type_hints: type | None) -> list[Any]:
        """Return the details, decoded using ``type_hints``.

        Returns an empty list if there are no details. For an error constructed
        locally, the original values are returned and ``type_hints`` are ignored.
        """
        if self._payload is None or self._data_converter is None:
            return list(self._values)
        if not self._payload.data:
            return []
        return self._data_converter.from_data(self._payload, list(type_hints))


class ApplicationError(_DetailsError):
    """A failure with a reason and optional details, raised from activity or workflow code.

    This is the counterpart of ``CustomError`` in the Go client. ``reason`` is
    recorded as the failure reason, which is what a RetryPolicy's
    ``non_retryable_error_reasons`` is matched against. ``details`` are encoded
    with the client's data converter, so workflows written with any Cadence
    client can decode them.

    ``failure_category`` and ``next_retry_delay`` are only supported for
    activity failures:

    - ``failure_category`` can influence retry and logging behavior
      independently of the RetryPolicy. Failures with
      ``FAILURE_CATEGORY_POLL`` are not logged as activity errors.
    - ``next_retry_delay`` overrides the delay until the next attempt of the
      activity. It does not influence whether the activity is retried, which is
      still determined by the RetryPolicy and the failure category. The delay
      is rounded up to whole seconds.

    When an activity or child workflow fails, workflow code receives an
    :class:`ActivityError` or :class:`ChildWorkflowError` whose
    ``cause`` is an ``ApplicationError``. Use :meth:`details` to decode its
    details. Decoding fails if the failure was not created from an
    ``ApplicationError`` (for example, an arbitrary Python exception, whose
    details are its traceback text).
    """

    def __init__(
        self,
        reason: str,
        *details: Any,
        failure_category: common_pb2.FailureCategory | None = None,
        next_retry_delay: timedelta | None = None,
    ) -> None:
        if next_retry_delay is not None and next_retry_delay < timedelta(0):
            raise ValueError("next_retry_delay must not be negative")
        super().__init__(reason, details)
        self.reason = reason
        self.failure_category = failure_category
        self.next_retry_delay = next_retry_delay

    @classmethod
    def _from_payload(
        cls,
        reason: str,
        payload: Payload,
        data_converter: "DataConverter",
        failure_category: common_pb2.FailureCategory | None = None,
        next_retry_delay: timedelta | None = None,
    ) -> Self:
        error = cls(
            reason,
            failure_category=failure_category,
            next_retry_delay=next_retry_delay,
        )
        error._payload = payload
        error._data_converter = data_converter
        return error

    def __str__(self) -> str:
        if self._payload is not None:
            if not self._payload.data:
                return self.reason
            # For a failure not created from an ApplicationError, this is the
            # remote exception's message and stack trace
            details = self._payload.data.decode("utf-8", errors="replace")
            return f"{self.reason}\n{details}"
        if self._values:
            return f"{self.reason} details={list(self._values)!r}"
        return self.reason


class CancelRequestedError(CadenceError):
    """Raised in an activity to report that it was canceled.

    Once a heartbeat reports that the workflow requested cancellation, the
    Activity API (e.g. :func:`cadence.activity.heartbeat`) raises it. This is how
    sync activities are told to stop. Async activities receive
    :class:`asyncio.CancelledError` instead, and only see this error if they
    suppress that and keep calling the Activity API.

    The worker reports it to Cadence as a cancellation. Raising it when
    cancellation wasn't requested fails the activity instead. It is never raised into workflow code: a workflow that
    canceled an activity receives :class:`asyncio.CancelledError`. It isn't a
    :class:`FailureError` because it never comes from workflow history.
    """

    def __init__(self) -> None:
        super().__init__("canceled")


class CadenceTimeoutError(_DetailsError):
    """An operation timed out. ``timeout_type`` identifies which timeout was exceeded.

    For an activity ``TIMEOUT_TYPE_HEARTBEAT`` timeout, :meth:`details` returns
    the details passed to the activity's last successful heartbeat, so the
    workflow can resume from that progress.
    """

    def __init__(self, timeout_type: workflow_pb2.TimeoutType, *details: Any) -> None:
        super().__init__(
            _enum_name(workflow_pb2.TimeoutType, timeout_type, "TIMEOUT_TYPE_"),
            details,
        )
        self.timeout_type = timeout_type

    @classmethod
    def _from_payload(
        cls,
        timeout_type: workflow_pb2.TimeoutType,
        payload: Payload,
        data_converter: "DataConverter",
    ) -> Self:
        error = cls(timeout_type)
        error._payload = payload
        error._data_converter = data_converter
        return error


class WorkflowCanceledError(_DetailsError):
    """A workflow was canceled. :meth:`details` returns the details it was canceled with.

    For a child workflow, this is the cause of a :class:`ChildWorkflowError` when
    something other than the parent canceled it. If the parent requested the
    cancellation, :class:`asyncio.CancelledError` is raised instead.
    """

    def __init__(self, *details: Any) -> None:
        super().__init__("canceled", details)

    @classmethod
    def _from_payload(cls, payload: Payload, data_converter: "DataConverter") -> Self:
        error = cls()
        error._payload = payload
        error._data_converter = data_converter
        return error


class TerminatedError(FailureError):
    """A workflow was terminated."""

    def __init__(self) -> None:
        super().__init__("terminated")


class ActivityError(FailureError):
    """An activity failed or timed out.

    ``cause`` is an :class:`ApplicationError` if the activity failed, or a
    :class:`CadenceTimeoutError` if it timed out. A cancellation requested by
    the workflow is raised as :class:`asyncio.CancelledError` instead.
    """

    def __init__(
        self,
        message: str,
        cause: ApplicationError | CadenceTimeoutError,
        *,
        activity_id: str,
        activity_type: str,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        # These errors are set on futures rather than raised, so chain them explicitly
        self.__cause__ = cause
        self.activity_id = activity_id
        self.activity_type = activity_type


class SignalExternalWorkflowError(FailureError):
    """A signal sent from a workflow could not be delivered.

    ``failure_cause`` is the ``SignalExternalWorkflowExecutionFailedCause``
    reported by Cadence, such as
    ``SIGNAL_EXTERNAL_WORKFLOW_EXECUTION_FAILED_CAUSE_UNKNOWN_EXTERNAL_WORKFLOW_EXECUTION``.
    """

    def __init__(
        self,
        message: str,
        failure_cause: workflow_pb2.SignalExternalWorkflowExecutionFailedCause,
        *,
        workflow_id: str,
        signal_name: str,
    ) -> None:
        super().__init__(message)
        self.failure_cause = failure_cause
        self.workflow_id = workflow_id
        self.signal_name = signal_name


class ChildWorkflowError(FailureError):
    """A child workflow failed, timed out, was terminated, or was canceled externally.

    ``cause`` is an :class:`ApplicationError` if the child workflow failed, a
    :class:`CadenceTimeoutError` if it timed out, a :class:`TerminatedError`
    if it was terminated, or a :class:`WorkflowCanceledError` if something other than
    this workflow canceled it. If this workflow requested the cancellation,
    :class:`asyncio.CancelledError` is raised instead.
    """

    def __init__(
        self,
        message: str,
        cause: FailureError | None,
        *,
        workflow_id: str,
        workflow_type: str,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        # These errors are set on futures rather than raised, so chain them explicitly
        self.__cause__ = cause
        self.workflow_id = workflow_id
        self.workflow_type = workflow_type


class StartChildWorkflowExecutionError(ChildWorkflowError):
    """A child workflow could not be started. ``cause`` is always ``None``.

    ``failure_cause`` is the ``ChildWorkflowExecutionFailedCause`` reported by
    Cadence, such as
    ``CHILD_WORKFLOW_EXECUTION_FAILED_CAUSE_WORKFLOW_ALREADY_RUNNING``.
    """

    def __init__(
        self,
        message: str,
        failure_cause: workflow_pb2.ChildWorkflowExecutionFailedCause,
        *,
        workflow_id: str,
        workflow_type: str,
    ) -> None:
        super().__init__(
            message, None, workflow_id=workflow_id, workflow_type=workflow_type
        )
        self.failure_cause = failure_cause


class CadenceRpcError(CadenceError):
    def __init__(self, message: str | None, code: grpc.StatusCode, *args):
        if message is None:
            super().__init__(code, *args)
        else:
            super().__init__(message, code, *args)
        self.code = code


class WorkflowExecutionAlreadyStartedError(CadenceRpcError):
    def __init__(
        self,
        message: str | None,
        code: grpc.StatusCode,
        start_request_id: str,
        run_id: str,
    ) -> None:
        super().__init__(message, code, start_request_id, run_id)
        self.start_request_id = start_request_id
        self.run_id = run_id


class EntityNotExistsError(CadenceRpcError):
    def __init__(
        self,
        message: str | None,
        code: grpc.StatusCode,
        current_cluster: str,
        active_cluster: str,
        active_clusters: list[str],
    ) -> None:
        super().__init__(
            message, code, current_cluster, active_cluster, active_clusters
        )
        self.current_cluster = current_cluster
        self.active_cluster = active_cluster
        self.active_clusters = active_clusters


class WorkflowExecutionAlreadyCompletedError(CadenceRpcError):
    pass


class DomainNotActiveError(CadenceRpcError):
    def __init__(
        self,
        message: str | None,
        code: grpc.StatusCode,
        domain: str,
        current_cluster: str,
        active_cluster: str,
        active_clusters: list[str],
    ) -> None:
        super().__init__(
            message, code, domain, current_cluster, active_cluster, active_clusters
        )
        self.domain = domain
        self.current_cluster = current_cluster
        self.active_cluster = active_cluster
        self.active_clusters = active_clusters


class ClientVersionNotSupportedError(CadenceRpcError):
    def __init__(
        self,
        message: str | None,
        code: grpc.StatusCode,
        feature_version: str,
        client_impl: str,
        supported_versions: str,
    ) -> None:
        super().__init__(
            message, code, feature_version, client_impl, supported_versions
        )
        self.feature_version = feature_version
        self.client_impl = client_impl
        self.supported_versions = supported_versions


class FeatureNotEnabledError(CadenceRpcError):
    def __init__(
        self, message: str | None, code: grpc.StatusCode, feature_flag: str
    ) -> None:
        super().__init__(message, code, feature_flag)
        self.feature_flag = feature_flag


class CancellationAlreadyRequestedError(CadenceRpcError):
    pass


class DomainAlreadyExistsError(CadenceRpcError):
    pass


class LimitExceededError(CadenceRpcError):
    pass


class QueryFailedError(CadenceRpcError):
    pass


class ServiceBusyError(CadenceRpcError):
    def __init__(self, message: str | None, code: grpc.StatusCode, reason: str) -> None:
        super().__init__(message, code, reason)
        self.reason = reason
