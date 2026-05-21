"""Adapt :class:`cadence.workflow.RetryPolicy` (TypedDict) to its protobuf wire form."""

from __future__ import annotations

from datetime import timedelta
from math import ceil
from typing import Mapping, cast

from google.protobuf.duration_pb2 import Duration

from cadence.api.v1 import common_pb2
from cadence.workflow import RetryPolicy


def _round_to_whole_seconds(delta: timedelta) -> timedelta:
    """Ceil-round a ``timedelta`` to whole seconds."""
    return timedelta(seconds=ceil(delta.total_seconds()))


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

    if (ii := policy.get("initial_interval")) is not None:
        _set_duration_field(out.initial_interval, cast(timedelta, ii))

    if (coef := policy.get("backoff_coefficient")) is not None:
        coef_f = cast(float, coef)
        if coef_f < 1.0:
            raise ValueError("backoff_coefficient must be >= 1.0 when provided")
        out.backoff_coefficient = coef_f

    if (mi := policy.get("maximum_interval")) is not None:
        _set_duration_field(out.maximum_interval, cast(timedelta, mi))

    if (ma := policy.get("maximum_attempts")) is not None:
        out.maximum_attempts = int(cast(int, ma))

    if (reasons := policy.get("non_retryable_error_reasons")) is not None:
        out.non_retryable_error_reasons.extend(cast(list[str], reasons))

    if (ei := policy.get("expiration_interval")) is not None:
        _set_duration_field(out.expiration_interval, cast(timedelta, ei))

    return out
