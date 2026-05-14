"""Round-trip and invariant tests for schedule proto mappers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cadence._internal.workflow.schedule_action import (
    schedule_action_from_proto,
    schedule_action_to_proto,
)
from cadence._internal.workflow.schedule_backfill import validate_backfill
from cadence._internal.workflow.schedule_policies import (
    schedule_policies_from_proto,
    schedule_policies_to_proto,
)
from cadence._internal.workflow.schedule_spec import (
    schedule_spec_from_proto,
    schedule_spec_to_proto,
)
from cadence._internal.workflow.schedule_state import (
    info_from_proto,
    state_from_proto,
)
from cadence.api.v1 import schedule_pb2
from cadence.data_converter import DefaultDataConverter
from cadence.schedule import (
    Backfill,
    ScheduleAction,
    ScheduleCatchUpPolicy,
    ScheduleOverlapPolicy,
    SchedulePolicies,
    ScheduleSpec,
    StartWorkflowAction,
)
from cadence.workflow import RetryPolicy

_DC = DefaultDataConverter()

# ---------------------------------------------------------------------------
# ScheduleSpec
# ---------------------------------------------------------------------------


class TestScheduleSpec:
    def test_round_trip_cron_only(self):
        spec: ScheduleSpec = {"cron_expression": "0 9 * * *"}
        proto = schedule_spec_to_proto(spec)
        assert proto is not None
        result = schedule_spec_from_proto(proto)
        assert result["cron_expression"] == "0 9 * * *"

    def test_round_trip_all_fields(self):
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        later = datetime(2026, 1, 1, tzinfo=timezone.utc)
        spec: ScheduleSpec = {
            "cron_expression": "CRON_TZ=UTC 0 6 * * *",
            "start_time": now,
            "end_time": later,
            "jitter": timedelta(seconds=30),
        }
        proto = schedule_spec_to_proto(spec)
        assert proto is not None
        result = schedule_spec_from_proto(proto)
        assert result["cron_expression"] == spec["cron_expression"]
        assert result["start_time"] == now
        assert result["end_time"] == later
        # jitter is ceil-rounded to whole seconds; 30s rounds to 30s
        assert result["jitter"] == timedelta(seconds=30)

    def test_none_returns_none(self):
        assert schedule_spec_to_proto(None) is None
        assert schedule_spec_to_proto({}) is None

    def test_naive_start_time_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            schedule_spec_to_proto({"start_time": datetime(2025, 1, 1)})

    def test_naive_end_time_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            schedule_spec_to_proto({"end_time": datetime(2025, 1, 1)})

    def test_sub_second_jitter_ceils_to_one_second(self):
        # Document and verify the ceil-rounding behaviour for jitter.
        # timedelta(milliseconds=500) has 0.5 total_seconds → ceil → 1 second.
        spec: ScheduleSpec = {"jitter": timedelta(milliseconds=500)}
        proto = schedule_spec_to_proto(spec)
        assert proto is not None
        result = schedule_spec_from_proto(proto)
        assert result["jitter"] == timedelta(seconds=1)


# ---------------------------------------------------------------------------
# ScheduleAction
# ---------------------------------------------------------------------------


class TestScheduleAction:
    def _minimal_action(self) -> ScheduleAction:
        return ScheduleAction(
            start_workflow=StartWorkflowAction(
                workflow_type="MyWorkflow",
                task_list="my-tl",
                execution_start_to_close_timeout=timedelta(hours=1),
            )
        )

    def test_round_trip_minimal(self):
        action = self._minimal_action()
        proto = schedule_action_to_proto(action, _DC)
        result = schedule_action_from_proto(proto)
        assert result["start_workflow"]["workflow_type"] == "MyWorkflow"
        assert result["start_workflow"]["task_list"] == "my-tl"
        # execution_start_to_close_timeout must survive the Duration round-trip
        assert result["start_workflow"][
            "execution_start_to_close_timeout"
        ] == timedelta(hours=1)

    def test_round_trip_with_prefix(self):
        action = ScheduleAction(
            start_workflow=StartWorkflowAction(
                workflow_type="MyWorkflow",
                task_list="tl",
                execution_start_to_close_timeout=timedelta(hours=1),
                workflow_id_prefix="daily-",
            )
        )
        proto = schedule_action_to_proto(action, _DC)
        result = schedule_action_from_proto(proto)
        assert result["start_workflow"]["workflow_id_prefix"] == "daily-"

    def test_round_trip_retry_policy(self):
        action = ScheduleAction(
            start_workflow=StartWorkflowAction(
                workflow_type="MyWorkflow",
                task_list="tl",
                execution_start_to_close_timeout=timedelta(hours=1),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_attempts=3,
                ),
            )
        )
        proto = schedule_action_to_proto(action, _DC)
        result = schedule_action_from_proto(proto)
        rp = result["start_workflow"]["retry_policy"]
        assert rp["initial_interval"] == timedelta(seconds=5)
        assert rp["maximum_attempts"] == 3

    def test_empty_action_raises(self):
        with pytest.raises(ValueError, match="exactly one action field"):
            schedule_action_to_proto({}, _DC)

    def test_missing_workflow_type_raises(self):
        with pytest.raises(ValueError, match="workflow_type is required"):
            schedule_action_to_proto(
                ScheduleAction(
                    start_workflow=StartWorkflowAction(
                        task_list="tl",
                        execution_start_to_close_timeout=timedelta(hours=1),
                    )
                ),
                _DC,
            )

    def test_missing_task_list_raises(self):
        with pytest.raises(ValueError, match="task_list is required"):
            schedule_action_to_proto(
                ScheduleAction(
                    start_workflow=StartWorkflowAction(
                        workflow_type="Wf",
                        execution_start_to_close_timeout=timedelta(hours=1),
                    )
                ),
                _DC,
            )

    def test_missing_execution_timeout_raises(self):
        with pytest.raises(
            ValueError, match="execution_start_to_close_timeout is required"
        ):
            schedule_action_to_proto(
                ScheduleAction(
                    start_workflow=StartWorkflowAction(
                        workflow_type="Wf",
                        task_list="tl",
                    )
                ),
                _DC,
            )


# ---------------------------------------------------------------------------
# SchedulePolicies
# ---------------------------------------------------------------------------


class TestSchedulePolicies:
    def test_round_trip_overlap_only(self):
        p: SchedulePolicies = {"overlap_policy": ScheduleOverlapPolicy.BUFFER}
        proto = schedule_policies_to_proto(p)
        assert proto is not None
        result = schedule_policies_from_proto(proto)
        assert result["overlap_policy"] == ScheduleOverlapPolicy.BUFFER

    def test_round_trip_all_fields(self):
        p: SchedulePolicies = {
            "overlap_policy": ScheduleOverlapPolicy.CONCURRENT,
            "catch_up_policy": ScheduleCatchUpPolicy.ONE,
            "catch_up_window": timedelta(hours=1),
            "pause_on_failure": True,
            "buffer_limit": 5,
            "concurrency_limit": 3,
        }
        proto = schedule_policies_to_proto(p)
        assert proto is not None
        result = schedule_policies_from_proto(proto)
        assert result["overlap_policy"] == ScheduleOverlapPolicy.CONCURRENT
        assert result["catch_up_policy"] == ScheduleCatchUpPolicy.ONE
        assert result["catch_up_window"] == timedelta(hours=1)
        assert result["pause_on_failure"] is True
        assert result["buffer_limit"] == 5
        assert result["concurrency_limit"] == 3

    def test_none_returns_none(self):
        assert schedule_policies_to_proto(None) is None
        assert schedule_policies_to_proto({}) is None

    def test_skip_new_plus_catch_up_all_raises(self):
        with pytest.raises(ValueError, match="SKIP_NEW.*ALL"):
            schedule_policies_to_proto(
                {
                    "overlap_policy": ScheduleOverlapPolicy.SKIP_NEW,
                    "catch_up_policy": ScheduleCatchUpPolicy.ALL,
                }
            )

    def test_negative_buffer_limit_raises(self):
        with pytest.raises(ValueError, match="buffer_limit"):
            schedule_policies_to_proto({"buffer_limit": -1})

    def test_negative_concurrency_limit_raises(self):
        with pytest.raises(ValueError, match="concurrency_limit"):
            schedule_policies_to_proto({"concurrency_limit": -1})

    def test_zero_limits_are_valid(self):
        # 0 means unlimited – must not raise
        proto = schedule_policies_to_proto({"buffer_limit": 0, "concurrency_limit": 0})
        assert proto is not None


# ---------------------------------------------------------------------------
# ScheduleState / ScheduleInfo (from_proto only – server-produced)
# ---------------------------------------------------------------------------


class TestScheduleState:
    def test_not_paused(self):
        proto = schedule_pb2.ScheduleState(paused=False)
        state = state_from_proto(proto)
        assert state.paused is False
        assert state.pause_info is None

    def test_paused_with_info(self):
        paused_at = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        pause_info_proto = schedule_pb2.SchedulePauseInfo(
            reason="maintenance",
            paused_by="user@example.com",
        )
        pause_info_proto.paused_at.FromDatetime(paused_at)
        proto = schedule_pb2.ScheduleState(paused=True, pause_info=pause_info_proto)
        state = state_from_proto(proto)
        assert state.paused is True
        assert state.pause_info is not None
        assert state.pause_info.reason == "maintenance"
        assert state.pause_info.paused_by == "user@example.com"
        assert state.pause_info.paused_at == paused_at


class TestScheduleInfo:
    def test_empty(self):
        proto = schedule_pb2.ScheduleInfo()
        info = info_from_proto(proto)
        assert info.total_runs == 0
        assert info.ongoing_backfills == ()

    def test_with_timestamps(self):
        t = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
        proto = schedule_pb2.ScheduleInfo(total_runs=42)
        proto.last_run_time.FromDatetime(t)
        info = info_from_proto(proto)
        assert info.total_runs == 42
        assert info.last_run_time == t

    def test_backfills_forwarded(self):
        bf_proto = schedule_pb2.BackfillInfo(
            backfill_id="bf-1",
            runs_completed=3,
            runs_total=10,
        )
        proto = schedule_pb2.ScheduleInfo()
        proto.ongoing_backfills.append(bf_proto)
        info = info_from_proto(proto)
        assert len(info.ongoing_backfills) == 1
        assert info.ongoing_backfills[0].backfill_id == "bf-1"
        assert info.ongoing_backfills[0].runs_total == 10


# ---------------------------------------------------------------------------
# Backfill validation
# ---------------------------------------------------------------------------


class TestValidateBackfill:
    _T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    _T1 = datetime(2025, 1, 2, tzinfo=timezone.utc)

    def test_valid_backfill_passes(self):
        validate_backfill(Backfill(start_time=self._T0, end_time=self._T1))

    def test_missing_start_time_raises(self):
        with pytest.raises(ValueError, match="start_time is required"):
            validate_backfill(Backfill(end_time=self._T1))

    def test_missing_end_time_raises(self):
        with pytest.raises(ValueError, match="end_time is required"):
            validate_backfill(Backfill(start_time=self._T0))

    def test_naive_start_time_raises(self):
        with pytest.raises(ValueError, match="start_time must be timezone-aware"):
            validate_backfill(
                Backfill(
                    start_time=datetime(2025, 1, 1),
                    end_time=self._T1,
                )
            )

    def test_naive_end_time_raises(self):
        with pytest.raises(ValueError, match="end_time must be timezone-aware"):
            validate_backfill(
                Backfill(
                    start_time=self._T0,
                    end_time=datetime(2025, 1, 2),
                )
            )

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="end_time must be strictly after"):
            validate_backfill(Backfill(start_time=self._T1, end_time=self._T0))

    def test_equal_times_raises(self):
        with pytest.raises(ValueError, match="end_time must be strictly after"):
            validate_backfill(Backfill(start_time=self._T0, end_time=self._T0))
