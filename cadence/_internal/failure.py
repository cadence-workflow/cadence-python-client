"""Conversion between Python exceptions and Cadence ``Failure`` messages.

Wire format:

- An :class:`ApplicationError` is recorded with its own reason, and its details
  encoded by the data converter. This matches ``CustomError`` in the Go client.
- Any other exception is recorded with its class name as the reason, and a
  UTF-8 message and stack trace as the details.
"""

import logging
from datetime import timedelta
from typing import Any
from traceback import format_exception

from cadence._internal.workflow.retry_policy import _set_duration_field
from cadence.api.v1 import common_pb2, decision, history, workflow_pb2
from cadence.api.v1.common_pb2 import Failure, FailureOptions, Payload
from cadence.data_converter import DataConverter
from cadence.error import (
    ActivityError,
    ApplicationError,
    CadenceTimeoutError,
    WorkflowCanceledError,
    ChildWorkflowError,
    FailureCategory,
    FailureError,
    SignalExternalWorkflowError,
    StartChildWorkflowExecutionError,
    TerminatedError,
    TimeoutType,
)

_logger = logging.getLogger(__name__)


def failure_from_exception(
    exc: BaseException, data_converter: DataConverter, *, include_options: bool
) -> Failure:
    """Convert an exception raised by activity or workflow code into a ``Failure``.

    ``include_options`` attaches an ``ApplicationError``'s failure category and
    next retry delay. They are only supported for activity failures.
    """
    if not isinstance(exc, ApplicationError):
        return Failure(reason=type(exc).__name__, details=_describe(exc))

    failure = Failure(reason=exc.reason, details=_encode_details(exc, data_converter))
    if include_options:
        options = _failure_options(exc)
        if options is not None:
            failure.options.CopyFrom(options)
    return failure


def application_error_from_failure(
    failure: Failure, data_converter: DataConverter
) -> ApplicationError:
    failure_category: FailureCategory | None = None
    next_retry_delay: timedelta | None = None
    if failure.HasField("options"):
        if failure.options.failure_category != common_pb2.FAILURE_CATEGORY_INVALID:
            failure_category = FailureCategory(failure.options.failure_category)
        if failure.options.HasField("next_retry_interval"):
            next_retry_delay = failure.options.next_retry_interval.ToTimedelta()
    return ApplicationError._from_payload(
        failure.reason,
        Payload(data=failure.details),
        data_converter,
        failure_category=failure_category,
        next_retry_delay=next_retry_delay,
    )


def activity_failed_error(
    event: history.ActivityTaskFailedEventAttributes,
    request: decision.ScheduleActivityTaskDecisionAttributes,
    data_converter: DataConverter,
) -> ActivityError:
    cause = application_error_from_failure(event.failure, data_converter)
    return _activity_error(
        "activity failed",
        request.activity_type.name,
        request.activity_id,
        cause,
    )


def activity_timed_out_error(
    event: history.ActivityTaskTimedOutEventAttributes,
    request: decision.ScheduleActivityTaskDecisionAttributes,
    data_converter: DataConverter,
) -> ActivityError:
    # The last failure is deliberately not exposed, matching the Java client.
    return _activity_error(
        "activity timed out",
        request.activity_type.name,
        request.activity_id,
        CadenceTimeoutError._from_payload(
            TimeoutType(event.timeout_type), event.details, data_converter
        ),
    )


def child_workflow_failed_error(
    event: history.ChildWorkflowExecutionFailedEventAttributes,
    data_converter: DataConverter,
) -> ChildWorkflowError:
    return _child_workflow_error(
        "child workflow failed",
        event.workflow_type.name,
        event.workflow_execution.workflow_id,
        application_error_from_failure(event.failure, data_converter),
    )


def child_workflow_timed_out_error(
    event: history.ChildWorkflowExecutionTimedOutEventAttributes,
) -> ChildWorkflowError:
    return _child_workflow_error(
        "child workflow timed out",
        event.workflow_type.name,
        event.workflow_execution.workflow_id,
        CadenceTimeoutError(TimeoutType(event.timeout_type)),
    )


def child_workflow_canceled_error(
    event: history.ChildWorkflowExecutionCanceledEventAttributes,
    data_converter: DataConverter,
) -> ChildWorkflowError:
    return _child_workflow_error(
        "child workflow canceled",
        event.workflow_type.name,
        event.workflow_execution.workflow_id,
        WorkflowCanceledError._from_payload(event.details, data_converter),
    )


def child_workflow_terminated_error(
    event: history.ChildWorkflowExecutionTerminatedEventAttributes,
) -> ChildWorkflowError:
    return _child_workflow_error(
        "child workflow terminated",
        event.workflow_type.name,
        event.workflow_execution.workflow_id,
        TerminatedError(),
    )


def start_child_workflow_failed_error(
    event: history.StartChildWorkflowExecutionFailedEventAttributes,
    request: decision.StartChildWorkflowExecutionDecisionAttributes,
) -> StartChildWorkflowExecutionError:
    cause = _enum_name(
        workflow_pb2.ChildWorkflowExecutionFailedCause,
        event.cause,
        "CHILD_WORKFLOW_EXECUTION_FAILED_CAUSE_",
    )
    return StartChildWorkflowExecutionError(
        f"start child workflow failed (workflow_type={request.workflow_type.name}, "
        f"workflow_id={event.workflow_id}): {cause}",
        failure_cause=event.cause,
        workflow_id=event.workflow_id,
        workflow_type=request.workflow_type.name,
    )


def signal_external_workflow_error(
    event: history.SignalExternalWorkflowExecutionFailedEventAttributes,
    request: decision.SignalExternalWorkflowExecutionDecisionAttributes,
) -> SignalExternalWorkflowError:
    cause = _enum_name(
        workflow_pb2.SignalExternalWorkflowExecutionFailedCause,
        event.cause,
        "SIGNAL_EXTERNAL_WORKFLOW_EXECUTION_FAILED_CAUSE_",
    )
    workflow_id = request.workflow_execution.workflow_id
    return SignalExternalWorkflowError(
        f"signal external workflow failed (signal_name={request.signal_name}, "
        f"workflow_id={workflow_id}): {cause}",
        failure_cause=event.cause,
        workflow_id=workflow_id,
        signal_name=request.signal_name,
    )


def activity_error_from_exception(
    exc: Exception,
    activity_type: str,
    activity_id: str,
    data_converter: DataConverter,
) -> ActivityError:
    """Build the error a workflow would see if an activity raised ``exc``.

    For running activities in-process, such as in the test environment.
    """
    failure = failure_from_exception(exc, data_converter, include_options=True)
    cause = application_error_from_failure(failure, data_converter)
    return _activity_error("activity failed", activity_type, activity_id, cause)


def child_workflow_error_from_exception(
    exc: Exception,
    workflow_type: str,
    workflow_id: str,
    data_converter: DataConverter,
) -> ChildWorkflowError:
    """Build the error a parent workflow would see if a child workflow raised ``exc``.

    For running child workflows in-process, such as in the test environment.
    """
    failure = failure_from_exception(exc, data_converter, include_options=False)
    cause = application_error_from_failure(failure, data_converter)
    return _child_workflow_error(
        "child workflow failed", workflow_type, workflow_id, cause
    )


def _child_workflow_error(
    summary: str,
    workflow_type: str,
    workflow_id: str,
    cause: FailureError,
) -> ChildWorkflowError:
    error = ChildWorkflowError(
        f"{summary} (workflow_type={workflow_type}, workflow_id={workflow_id}): "
        f"{cause}",
        workflow_id=workflow_id,
        workflow_type=workflow_type,
    )
    # These errors are set on futures rather than raised, so chain them explicitly
    error.__cause__ = cause
    return error


def _activity_error(
    summary: str,
    activity_type: str,
    activity_id: str,
    cause: ApplicationError | CadenceTimeoutError,
) -> ActivityError:
    error = ActivityError(
        f"{summary} (activity_type={activity_type}, activity_id={activity_id}): "
        f"{cause}",
        activity_id=activity_id,
        activity_type=activity_type,
    )
    # These errors are set on futures rather than raised, so chain them explicitly
    error.__cause__ = cause
    return error


def _enum_name(enum_type: Any, value: int, prefix: str) -> str:
    try:
        name: str = enum_type.Name(value)
    except ValueError:
        return str(value)
    return name.removeprefix(prefix)


def _describe(exc: BaseException) -> bytes:
    stacktrace = "".join(format_exception(exc))
    return f"message: {exc}\nstacktrace: {stacktrace}".encode("utf-8")


def _encode_details(error: ApplicationError, data_converter: DataConverter) -> bytes:
    # A failure received from Cadence is passed through unchanged
    if error._payload is not None:
        return error._payload.data
    if not error.has_details():
        return b""
    try:
        return data_converter.to_data(error.details()).data
    except Exception as e:
        _logger.warning("Failed to encode ApplicationError details", exc_info=True)
        return f"failed to encode ApplicationError details: {e!r}".encode("utf-8")


def _failure_options(error: ApplicationError) -> FailureOptions | None:
    if error.failure_category is None and error.next_retry_delay is None:
        return None
    options = FailureOptions()
    if error.failure_category is not None:
        options.failure_category = error.failure_category.value
    if error.next_retry_delay is not None:
        _set_duration_field(options.next_retry_interval, error.next_retry_delay)
    return options
