from datetime import timedelta
from typing import Mapping, cast

import pytest
from google.protobuf.json_format import MessageToDict

from cadence._internal.workflow.retry_policy import retry_policy_to_proto


def test_retry_policy_none_and_empty():
    assert retry_policy_to_proto(None) is None
    assert retry_policy_to_proto({}) is None


def test_retry_policy_rounds_durations_up_to_seconds():
    p = retry_policy_to_proto(
        {
            "initial_interval": timedelta(milliseconds=500),
            "maximum_interval": timedelta(seconds=2, microseconds=1),
            "expiration_interval": timedelta(seconds=30),
        }
    )
    assert p is not None
    assert p.initial_interval.seconds == 1
    assert p.maximum_interval.seconds == 3
    assert p.expiration_interval.seconds == 30


def test_retry_policy_maximum_interval_none_omits_field():
    p = retry_policy_to_proto(
        cast(
            Mapping[str, object],
            {
                "initial_interval": timedelta(seconds=1),
                "maximum_interval": None,
            },
        )
    )
    assert p is not None
    assert not p.HasField("maximum_interval")


def test_retry_policy_backoff_coefficient_validation():
    with pytest.raises(ValueError, match="backoff_coefficient"):
        retry_policy_to_proto({"backoff_coefficient": 0.5})

    p = retry_policy_to_proto(
        {"backoff_coefficient": 1.0, "initial_interval": timedelta(seconds=1)}
    )
    assert p is not None
    assert p.backoff_coefficient == 1.0


def test_retry_policy_maximum_attempts_and_non_retryable():
    p = retry_policy_to_proto(
        {
            "maximum_attempts": 0,
            "non_retryable_error_reasons": ["a", "b"],
        }
    )
    assert p is not None
    assert p.maximum_attempts == 0
    assert list(p.non_retryable_error_reasons) == ["a", "b"]


def test_retry_policy_backoff_omitted_not_explicitly_set_in_dict():
    p = retry_policy_to_proto({"initial_interval": timedelta(seconds=1)})
    assert p is not None
    d = MessageToDict(p, preserving_proto_field_name=True)
    assert "backoff_coefficient" not in d


def test_retry_policy_explicit_none_fields_are_omitted():
    p = retry_policy_to_proto(
        cast(
            Mapping[str, object],
            {
                "initial_interval": None,
                "backoff_coefficient": None,
                "maximum_interval": None,
                "maximum_attempts": None,
                "non_retryable_error_reasons": None,
                "expiration_interval": None,
            },
        )
    )
    assert p is not None
    assert not p.HasField("initial_interval")
    assert not p.HasField("maximum_interval")
    assert not p.HasField("expiration_interval")
    d = MessageToDict(p, preserving_proto_field_name=True)
    assert "backoff_coefficient" not in d
    assert "maximum_attempts" not in d
    assert "non_retryable_error_reasons" not in d
