from datetime import timedelta

import pytest

from cadence._internal.failure import (
    application_error_from_failure,
    failure_from_exception,
)
from cadence.api.v1.common_pb2 import FAILURE_CATEGORY_POLL, Failure
from cadence.data_converter import DefaultDataConverter
from cadence.error import ApplicationError, FailureCategory

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
        ApplicationError("my-reason"), DC, include_options=False
    )

    assert failure == Failure(reason="my-reason")
    assert not application_error_from_failure(failure, DC).has_details()


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
        failure_category=FailureCategory.POLL,
        next_retry_delay=timedelta(seconds=5),
    )

    with_options = failure_from_exception(error, DC, include_options=True)
    without_options = failure_from_exception(error, DC, include_options=False)

    assert with_options.options.failure_category == FAILURE_CATEGORY_POLL
    assert with_options.options.next_retry_interval.ToTimedelta() == timedelta(
        seconds=5
    )
    assert not without_options.HasField("options")


def test_no_failure_options_when_unset():
    failure = failure_from_exception(
        ApplicationError("my-reason"), DC, include_options=True
    )

    assert not failure.HasField("options")


def test_next_retry_delay_only():
    failure = failure_from_exception(
        ApplicationError("my-reason", next_retry_delay=timedelta(seconds=3)),
        DC,
        include_options=True,
    )

    assert failure.options.next_retry_interval.ToTimedelta() == timedelta(seconds=3)
    received = application_error_from_failure(failure, DC)
    assert received.failure_category is None
    assert received.next_retry_delay == timedelta(seconds=3)


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


def test_application_error_validation():
    with pytest.raises(ValueError):
        ApplicationError("my-reason", next_retry_delay=timedelta(seconds=-1))
    with pytest.raises(TypeError):
        ApplicationError("my-reason", failure_category=1)  # type: ignore[arg-type]
