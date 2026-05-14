"""Convert ScheduleSpec TypedDict to/from protobuf."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Mapping, cast

from google.protobuf.duration_pb2 import Duration
from google.protobuf.timestamp_pb2 import Timestamp

from cadence.api.v1 import schedule_pb2
from cadence.schedule import ScheduleSpec


def _require_tz_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None:
        raise ValueError(
            f"{name} must be timezone-aware. "
            "Use datetime.now(timezone.utc) or datetime(..., tzinfo=timezone.utc)"
        )


def schedule_spec_to_proto(
    spec: ScheduleSpec | Mapping[str, object] | None,
) -> schedule_pb2.ScheduleSpec | None:
    """Convert a ScheduleSpec TypedDict to protobuf, or None if not provided."""
    if spec is None or (isinstance(spec, Mapping) and len(spec) == 0):
        return None

    out = schedule_pb2.ScheduleSpec()

    if (cron := spec.get("cron_expression")) is not None:
        out.cron_expression = str(cron)

    if (start := spec.get("start_time")) is not None:
        start_dt = cast(datetime, start)
        _require_tz_aware(start_dt, "start_time")
        ts = Timestamp()
        ts.FromDatetime(start_dt)
        out.start_time.CopyFrom(ts)

    if (end := spec.get("end_time")) is not None:
        end_dt = cast(datetime, end)
        _require_tz_aware(end_dt, "end_time")
        ts = Timestamp()
        ts.FromDatetime(end_dt)
        out.end_time.CopyFrom(ts)

    if (jitter := spec.get("jitter")) is not None:
        jitter_td = cast(timedelta, jitter)
        d = Duration()
        d.FromTimedelta(timedelta(seconds=ceil(jitter_td.total_seconds())))
        out.jitter.CopyFrom(d)

    return out


def schedule_spec_from_proto(proto: schedule_pb2.ScheduleSpec) -> ScheduleSpec:
    """Convert a protobuf ScheduleSpec to a ScheduleSpec TypedDict."""
    spec: ScheduleSpec = {}

    if proto.cron_expression:
        spec["cron_expression"] = proto.cron_expression

    if proto.HasField("start_time"):
        spec["start_time"] = proto.start_time.ToDatetime(tzinfo=timezone.utc)

    if proto.HasField("end_time"):
        spec["end_time"] = proto.end_time.ToDatetime(tzinfo=timezone.utc)

    if proto.HasField("jitter"):
        spec["jitter"] = proto.jitter.ToTimedelta()

    return spec
