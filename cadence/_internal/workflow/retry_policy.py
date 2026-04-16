"""Adapt :class:`cadence.workflow.RetryPolicy` (TypedDict) to its protobuf wire form."""

from __future__ import annotations

from datetime import timedelta
from math import ceil
from typing import Mapping, cast

from google.protobuf.duration_pb2 import Duration

from cadence.api.v1 import common_pb2
from cadence.workflow import RetryPolicy

_round_to_whole_seconds = lambda delta: timedelta(seconds=ceil(delta.total_seconds()))

def _set_duration_field(target: Duration, delta: timedelta) -> None:
    """Write ``delta``, ceil-rounded to whole seconds, into a proto ``Duration`` field."""
    d = Duration()
    d.FromTimedelta(_round_to_whole_seconds(delta))
    target.CopyFrom(d)


def retry_policy_to_proto(
    policy: RetryPolicy | Mapping[str, object] | None,
) -> common_pb2.RetryPolicy | None:
    """Convert a user retry policy to protobuf, or ``None`` if no policy was provided.

    ``None`` and an empty mapping both map to ``None`` so that the server applies its
    own defaults instead of receiving an explicit empty policy. Durations are ceiled
    to whole seconds to match the server's resolution and the Go/Java SDKs.
    """
    if policy is None or (isinstance(policy, Mapping) and len(policy) == 0):
        return None

    out = common_pb2.RetryPolicy()

    if "initial_interval" in policy:
        _set_duration_field(
            out.initial_interval, cast(timedelta, policy["initial_interval"])
        )

    if "backoff_coefficient" in policy:
        coef = cast(float, policy["backoff_coefficient"])
        if coef < 1.0:
            raise ValueError("backoff_coefficient must be >= 1.0 when provided")
        out.backoff_coefficient = coef

    if (mi := policy.get("maximum_interval")) is not None:
        _set_duration_field(out.maximum_interval, cast(timedelta, mi))

    if "maximum_attempts" in policy:
        out.maximum_attempts = int(cast(int, policy["maximum_attempts"]))

    if "non_retryable_error_reasons" in policy:
        out.non_retryable_error_reasons.extend(
            cast(list[str], policy["non_retryable_error_reasons"])
        )

    if (ei := policy.get("expiration_interval")) is not None:
        _set_duration_field(out.expiration_interval, cast(timedelta, ei))

    return out
