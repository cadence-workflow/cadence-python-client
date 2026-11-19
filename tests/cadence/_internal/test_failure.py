from datetime import timedelta

import pytest

from cadence._internal.failure import (
    activity_timed_out_error,
    application_error_from_failure,
    child_workflow_error_from_exception,
    failure_from_exception,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import FAILURE_CATEGORY_POLL, Failure, FailureOptions
from cadence.data_converter import DefaultDataConverter
from cadence.error import ApplicationError, CadenceTimeoutError

DC = DefaultDataConverter()


def test_application_error_details_round_trip():
    error = ApplicationError("my-reason", {"a": 1}, [2, 3], "four")

    failure = failure_from_exception(error, DC, include_options=False)
    received = application_error_from_failure(failure, DC)

    assert failure.reason == "my-reason"
    assert received.reason == "my-reason"
    assert received.has_details()
    assert received.details(dict, list[int], str) == [{"a": 1}, [2, 3], "four"]


def test_application_error_without_details():
    failure = failure_from_exception(
        ApplicationError("my-reason"), DC, include_options=True
    )

    assert failure == Failure(reason="my-reason")
    received = application_error_from_failure(failure, DC)
    assert not received.has_details()
    assert received.details(int, str) == []


def test_other_exception_reason_is_class_name_and_details_are_text():
    def fail() -> None:
        raise KeyError("missing")

    try:
        fail()
    except KeyError as e:
        failure = failure_from_exception(e, DC, include_options=True)

    details = failure.details.decode()
    assert failure.reason == "KeyError"
    assert details.startswith("message: 'missing'\nstacktrace: ")
    assert 'raise KeyError("missing")' in details
    assert not failure.HasField("options")


def test_received_application_error_is_passed_through_unchanged():
    original = Failure(reason="from-go", details=b'{"Go":"encoded"}')
    received = application_error_from_failure(original, DC)

    assert failure_from_exception(received, DC, include_options=False) == original


def test_failure_options_only_included_when_requested():
    error = ApplicationError(
        "my-reason",
        failure_category=FAILURE_CATEGORY_POLL,
        next_retry_delay=timedelta(seconds=5),
    )

    with_options = failure_from_exception(error, DC, include_options=True)
    without_options = failure_from_exception(error, DC, include_options=False)

    assert with_options.options.failure_category == FAILURE_CATEGORY_POLL
    assert with_options.options.next_retry_interval.ToTimedelta() == timedelta(
        seconds=5
    )
    assert not without_options.HasField("options")


def test_next_retry_delay_rounds_up_to_whole_seconds():
    failure = failure_from_exception(
        ApplicationError("my-reason", next_retry_delay=timedelta(seconds=1.2)),
        DC,
        include_options=True,
    )

    assert failure.options.next_retry_interval.ToTimedelta() == timedelta(seconds=2)


def test_unencodable_details_keep_reason():
    failure = failure_from_exception(
        ApplicationError("my-reason", object()), DC, include_options=False
    )

    assert failure.reason == "my-reason"
    assert b"failed to encode ApplicationError details" in failure.details


def test_received_application_error_str_includes_details_text():
    received = application_error_from_failure(
        Failure(reason="RuntimeError", details=b"message: boom"), DC
    )

    assert str(received) == "RuntimeError\nmessage: boom"


def test_nested_failure_describes_original_error_once():
    error: Exception = ValueError("boom")
    for level in range(3):
        error = child_workflow_error_from_exception(
            error, "ChildWorkflow", f"child-{level}", DC
        )

    failure = failure_from_exception(error, DC, include_options=False)

    assert failure.details.decode().count("ValueError: boom") == 1


def test_unknown_failure_category_is_passed_through():
    failure = Failure(reason="my-reason", options=FailureOptions(failure_category=99))  # type: ignore[arg-type]

    assert application_error_from_failure(failure, DC).failure_category == 99


def test_unknown_timeout_type_is_passed_through():
    error = activity_timed_out_error(
        history.ActivityTaskTimedOutEventAttributes(timeout_type=99),  # type: ignore[arg-type]
        decision.ScheduleActivityTaskDecisionAttributes(activity_id="a"),
        DC,
    )

    assert isinstance(error.cause, CadenceTimeoutError)
    assert error.cause.timeout_type == 99


def test_application_error_validation():
    with pytest.raises(ValueError):
        ApplicationError("my-reason", next_retry_delay=timedelta(seconds=-1))
