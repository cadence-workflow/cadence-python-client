from datetime import timedelta
from enum import IntEnum
from typing import TYPE_CHECKING, Any

import grpc

from cadence.api.v1 import common_pb2, workflow_pb2
from cadence.api.v1.common_pb2 import Payload

if TYPE_CHECKING:
    from cadence.data_converter import DataConverter


class FailureCategory(IntEnum):
    """Classifies an activity failure, independently of the activity's RetryPolicy.

    The category can influence retry and logging behavior. It is currently only
    supported for activity failures.
    """

    POLL = common_pb2.FAILURE_CATEGORY_POLL
    """An expected failure, such as a polling activity with nothing to do yet.
    The worker does not log it as an activity error."""
    STANDARD = common_pb2.FAILURE_CATEGORY_STANDARD
    FATAL = common_pb2.FAILURE_CATEGORY_FATAL


class TimeoutType(IntEnum):
    START_TO_CLOSE = workflow_pb2.TIMEOUT_TYPE_START_TO_CLOSE
    SCHEDULE_TO_START = workflow_pb2.TIMEOUT_TYPE_SCHEDULE_TO_START
    SCHEDULE_TO_CLOSE = workflow_pb2.TIMEOUT_TYPE_SCHEDULE_TO_CLOSE
    HEARTBEAT = workflow_pb2.TIMEOUT_TYPE_HEARTBEAT


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


class ActivityCancelledError(CadenceError):
    def __init__(self, *details: Any) -> None:
        super().__init__("Activity cancelled")
        self.details = list(details)


class FailureError(CadenceError):
    """Base class for failures that are recorded in Cadence and raised into workflow code."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ApplicationError(FailureError):
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
      :attr:`FailureCategory.POLL` are not logged as activity errors.
    - ``next_retry_delay`` overrides the delay until the next attempt of the
      activity. It does not influence whether the activity is retried, which is
      still determined by the RetryPolicy and the failure category. The delay
      is rounded up to whole seconds.

    When an activity or child workflow fails, workflow code receives an
    :class:`ActivityError` or :class:`ChildWorkflowError` whose
    ``cause`` is an ``ApplicationError``. Use :meth:`details` to decode its
    details.
    """

    def __init__(
        self,
        reason: str,
        *details: Any,
        failure_category: FailureCategory | None = None,
        next_retry_delay: timedelta | None = None,
    ) -> None:
        if failure_category is not None and not isinstance(
            failure_category, FailureCategory
        ):
            raise TypeError(
                f"failure_category must be a FailureCategory, got {failure_category!r}"
            )
        if next_retry_delay is not None and next_retry_delay < timedelta(0):
            raise ValueError("next_retry_delay must not be negative")
        message = f"{reason} details={list(details)!r}" if details else reason
        super().__init__(message)
        self.reason = reason
        self.failure_category = failure_category
        self.next_retry_delay = next_retry_delay
        self._values: tuple[Any, ...] = details
        self._payload: Payload | None = None
        self._data_converter: "DataConverter | None" = None

    @staticmethod
    def _from_payload(
        reason: str,
        payload: Payload,
        data_converter: "DataConverter",
        failure_category: FailureCategory | None = None,
        next_retry_delay: timedelta | None = None,
    ) -> "ApplicationError":
        error = ApplicationError(
            reason,
            failure_category=failure_category,
            next_retry_delay=next_retry_delay,
        )
        error._payload = payload
        error._data_converter = data_converter
        if payload.data:
            error.message = (
                f"{reason}\n{payload.data.decode('utf-8', errors='replace')}"
            )
            error.args = (error.message,)
        return error

    def has_details(self) -> bool:
        if self._payload is not None:
            return bool(self._payload.data)
        return bool(self._values)

    def details(self, *type_hints: type | None) -> list[Any]:
        """Return the details of this failure.

        For a failure received from Cadence, the details are decoded with the
        data converter using ``type_hints``. Decoding fails if the failure was
        not created from an ``ApplicationError`` (for example, an arbitrary
        Python exception, whose details are its traceback text). For an
        ``ApplicationError`` constructed locally, the original values are
        returned and ``type_hints`` are ignored.
        """
        if self._payload is None or self._data_converter is None:
            return list(self._values)
        return self._data_converter.from_data(self._payload, list(type_hints))


class _EncodedDetails:
    """Details that are either local values or a payload received from Cadence."""

    def _init_details(self, values: tuple[Any, ...]) -> None:
        self._values = values
        self._payload: Payload | None = None
        self._data_converter: "DataConverter | None" = None

    def _set_payload(self, payload: Payload, data_converter: "DataConverter") -> None:
        self._payload = payload
        self._data_converter = data_converter

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


class CadenceTimeoutError(_EncodedDetails, FailureError):
    """An operation timed out. ``timeout_type`` identifies which timeout was exceeded.

    For an activity ``HEARTBEAT`` timeout, :meth:`details` returns the details
    passed to the activity's last successful heartbeat, so the workflow can
    resume from that progress.
    """

    def __init__(self, timeout_type: TimeoutType, *details: Any) -> None:
        super().__init__(timeout_type.name)
        self.timeout_type = timeout_type
        self._init_details(details)

    @staticmethod
    def _from_payload(
        timeout_type: TimeoutType,
        payload: Payload,
        data_converter: "DataConverter",
    ) -> "CadenceTimeoutError":
        error = CadenceTimeoutError(timeout_type)
        error._set_payload(payload, data_converter)
        return error


class WorkflowCanceledError(_EncodedDetails, FailureError):
    """A workflow was canceled. :meth:`details` returns the details it was canceled with.

    For a child workflow, this is the cause of a :class:`ChildWorkflowError` when
    something other than the parent canceled it. If the parent requested the
    cancellation, :class:`asyncio.CancelledError` is raised instead.
    """

    def __init__(self, *details: Any) -> None:
        super().__init__("canceled")
        self._init_details(details)

    @staticmethod
    def _from_payload(
        payload: Payload, data_converter: "DataConverter"
    ) -> "WorkflowCanceledError":
        error = WorkflowCanceledError()
        error._set_payload(payload, data_converter)
        return error


class TerminatedError(FailureError):
    """A workflow was terminated."""

    def __init__(self) -> None:
        super().__init__("terminated")


class ActivityError(FailureError):
    """An activity failed or timed out.

    ``cause`` is an :class:`ApplicationError` if the activity failed, or a
    :class:`CadenceTimeoutError` if it timed out. Cancellation is raised as
    :class:`asyncio.CancelledError` instead.
    """

    def __init__(self, message: str, *, activity_id: str, activity_type: str) -> None:
        super().__init__(message)
        self.activity_id = activity_id
        self.activity_type = activity_type

    @property
    def cause(self) -> BaseException | None:
        return self.__cause__


class SignalExternalWorkflowError(FailureError):
    """A signal sent from a workflow could not be delivered.

    ``failure_cause`` is the ``SignalExternalWorkflowExecutionFailedCause``
    reported by Cadence, such as ``UNKNOWN_EXTERNAL_WORKFLOW_EXECUTION``.
    """

    def __init__(
        self,
        message: str,
        failure_cause: int,
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

    def __init__(self, message: str, *, workflow_id: str, workflow_type: str) -> None:
        super().__init__(message)
        self.workflow_id = workflow_id
        self.workflow_type = workflow_type

    @property
    def cause(self) -> BaseException | None:
        return self.__cause__


class StartChildWorkflowExecutionError(ChildWorkflowError):
    """A child workflow could not be started.

    ``failure_cause`` is the ``ChildWorkflowExecutionFailedCause`` reported by
    Cadence, such as ``WORKFLOW_ALREADY_RUNNING``.
    """

    def __init__(
        self,
        message: str,
        failure_cause: int,
        *,
        workflow_id: str,
        workflow_type: str,
    ) -> None:
        super().__init__(message, workflow_id=workflow_id, workflow_type=workflow_type)
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
