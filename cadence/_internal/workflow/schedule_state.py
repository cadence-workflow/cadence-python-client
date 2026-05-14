"""Convert schedule state/info protos to public frozen dataclasses."""

from __future__ import annotations

from datetime import timezone

from cadence.api.v1 import schedule_pb2
from cadence.schedule import (
    BackfillInfo,
    ScheduleInfo,
    SchedulePauseInfo,
    ScheduleState,
)


def pause_info_from_proto(proto: schedule_pb2.SchedulePauseInfo) -> SchedulePauseInfo:
    paused_at = None
    if proto.HasField("paused_at"):
        paused_at = proto.paused_at.ToDatetime(tzinfo=timezone.utc)
    return SchedulePauseInfo(
        reason=proto.reason,
        paused_at=paused_at,
        paused_by=proto.paused_by,
    )


def state_from_proto(proto: schedule_pb2.ScheduleState) -> ScheduleState:
    pause_info = None
    if proto.HasField("pause_info"):
        pause_info = pause_info_from_proto(proto.pause_info)
    return ScheduleState(
        paused=proto.paused,
        pause_info=pause_info,
    )


def backfill_info_from_proto(proto: schedule_pb2.BackfillInfo) -> BackfillInfo:
    start_time = None
    end_time = None
    if proto.HasField("start_time"):
        start_time = proto.start_time.ToDatetime(tzinfo=timezone.utc)
    if proto.HasField("end_time"):
        end_time = proto.end_time.ToDatetime(tzinfo=timezone.utc)
    return BackfillInfo(
        backfill_id=proto.backfill_id,
        start_time=start_time,
        end_time=end_time,
        runs_completed=proto.runs_completed,
        runs_total=proto.runs_total,
    )


def info_from_proto(proto: schedule_pb2.ScheduleInfo) -> ScheduleInfo:
    last_run_time = None
    next_run_time = None
    create_time = None
    last_update_time = None

    if proto.HasField("last_run_time"):
        last_run_time = proto.last_run_time.ToDatetime(tzinfo=timezone.utc)
    if proto.HasField("next_run_time"):
        next_run_time = proto.next_run_time.ToDatetime(tzinfo=timezone.utc)
    if proto.HasField("create_time"):
        create_time = proto.create_time.ToDatetime(tzinfo=timezone.utc)
    if proto.HasField("last_update_time"):
        last_update_time = proto.last_update_time.ToDatetime(tzinfo=timezone.utc)

    ongoing_backfills = tuple(
        backfill_info_from_proto(b) for b in proto.ongoing_backfills
    )

    return ScheduleInfo(
        last_run_time=last_run_time,
        next_run_time=next_run_time,
        total_runs=proto.total_runs,
        create_time=create_time,
        last_update_time=last_update_time,
        ongoing_backfills=ongoing_backfills,
    )
