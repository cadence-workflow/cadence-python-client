"""Convert SchedulePolicies TypedDict to/from protobuf."""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping, cast

from cadence.api.v1 import schedule_pb2
from cadence._internal.workflow.retry_policy import _set_duration_field
from cadence.schedule import (
    ScheduleCatchUpPolicy,
    ScheduleOverlapPolicy,
    SchedulePolicies,
)

# Wire integer values – kept local to avoid importing from cadence.api.v1 in schedule.py.
_OVERLAP_SKIP_NEW = int(schedule_pb2.SCHEDULE_OVERLAP_POLICY_SKIP_NEW)
_CATCH_UP_ALL = int(schedule_pb2.SCHEDULE_CATCH_UP_POLICY_ALL)


def _validate_policies(policies: SchedulePolicies | Mapping[str, object]) -> None:
    overlap = policies.get("overlap_policy")
    catch_up = policies.get("catch_up_policy")

    if (
        overlap is not None
        and int(cast(ScheduleOverlapPolicy, overlap)) == _OVERLAP_SKIP_NEW
        and catch_up is not None
        and int(cast(ScheduleCatchUpPolicy, catch_up)) == _CATCH_UP_ALL
    ):
        raise ValueError(
            "overlap_policy=SKIP_NEW combined with catch_up_policy=ALL is invalid: "
            "SKIP_NEW means new runs are dropped, so there is nothing to catch up on."
        )

    buffer_limit = policies.get("buffer_limit")
    if buffer_limit is not None and int(cast(int, buffer_limit)) < 0:
        raise ValueError("buffer_limit must be >= 0 (0 means unlimited)")

    concurrency_limit = policies.get("concurrency_limit")
    if concurrency_limit is not None and int(cast(int, concurrency_limit)) < 0:
        raise ValueError("concurrency_limit must be >= 0 (0 means unlimited)")


def schedule_policies_to_proto(
    policies: SchedulePolicies | Mapping[str, object] | None,
) -> schedule_pb2.SchedulePolicies | None:
    """Convert SchedulePolicies to protobuf, or None if not provided."""
    if policies is None or (isinstance(policies, Mapping) and len(policies) == 0):
        return None

    _validate_policies(policies)

    out = schedule_pb2.SchedulePolicies()

    if (overlap := policies.get("overlap_policy")) is not None:
        out.overlap_policy = cast(
            schedule_pb2.ScheduleOverlapPolicy,
            int(cast(ScheduleOverlapPolicy, overlap)),
        )

    if (catch_up := policies.get("catch_up_policy")) is not None:
        out.catch_up_policy = cast(
            schedule_pb2.ScheduleCatchUpPolicy,
            int(cast(ScheduleCatchUpPolicy, catch_up)),
        )

    if (window := policies.get("catch_up_window")) is not None:
        _set_duration_field(out.catch_up_window, cast(timedelta, window))

    if (pof := policies.get("pause_on_failure")) is not None:
        out.pause_on_failure = bool(pof)

    if (bl := policies.get("buffer_limit")) is not None:
        out.buffer_limit = int(cast(int, bl))

    if (cl := policies.get("concurrency_limit")) is not None:
        out.concurrency_limit = int(cast(int, cl))

    return out


def schedule_policies_from_proto(
    proto: schedule_pb2.SchedulePolicies,
) -> SchedulePolicies:
    """Convert a protobuf SchedulePolicies to a SchedulePolicies TypedDict."""
    policies: SchedulePolicies = {}

    if proto.overlap_policy:
        policies["overlap_policy"] = ScheduleOverlapPolicy(proto.overlap_policy)

    if proto.catch_up_policy:
        policies["catch_up_policy"] = ScheduleCatchUpPolicy(proto.catch_up_policy)

    if proto.HasField("catch_up_window"):
        policies["catch_up_window"] = proto.catch_up_window.ToTimedelta()

    if proto.pause_on_failure:
        policies["pause_on_failure"] = proto.pause_on_failure

    if proto.buffer_limit:
        policies["buffer_limit"] = proto.buffer_limit

    if proto.concurrency_limit:
        policies["concurrency_limit"] = proto.concurrency_limit

    return policies
