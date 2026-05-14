"""Public API types for Cadence Schedules.

  These types are the public surface for schedule management. They do NOT import
  from ``cadence.api.v1.*``; proto conversion is handled in
  ``cadence._internal.workflow.schedule_*``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, TypedDict

from cadence.error import EntityNotExistsError, WorkflowExecutionAlreadyStartedError
from cadence.workflow import RetryPolicy


# ---------------------------------------------------------------------------
# Enums – integer values equal the proto wire codes so mappers can cast directly.
# ---------------------------------------------------------------------------


class ScheduleOverlapPolicy(enum.IntEnum):
    """What to do when a schedule would start a new run but one is already running."""

    INVALID = 0
    SKIP_NEW = 1
    BUFFER = 2
    CONCURRENT = 3
    CANCEL_PREVIOUS = 4
    TERMINATE_PREVIOUS = 5


class ScheduleCatchUpPolicy(enum.IntEnum):
    """What to do with missed runs when a paused schedule is resumed."""

    INVALID = 0
    SKIP = 1
    ONE = 2
    ALL = 3


# ---------------------------------------------------------------------------
# Input TypedDicts – option bags for create / update operations.
# ---------------------------------------------------------------------------


class ScheduleSpec(TypedDict, total=False):
    """When a schedule fires.

    All datetime values must be timezone-aware.
    """

    cron_expression: str
    start_time: datetime
    end_time: datetime
    jitter: timedelta


class StartWorkflowAction(TypedDict, total=False):
    """The workflow that a schedule will start on each fire.

    ``workflow_type``, ``task_list``, and ``execution_start_to_close_timeout``
    are required. ``args`` values must be JSON-round-trippable because the
    server re-encodes the action with ``encoding/json`` for ContinueAsNew.
    Args are NOT decoded when reading back from DescribeSchedule.
    """

    workflow_type: str
    task_list: str
    workflow_id_prefix: str
    execution_start_to_close_timeout: timedelta
    task_start_to_close_timeout: timedelta
    args: tuple[Any, ...]
    retry_policy: RetryPolicy


class ScheduleAction(TypedDict, total=False):
    """The action taken when a schedule fires.

    Exactly one field must be set. Only ``start_workflow`` is supported today.
    """

    start_workflow: StartWorkflowAction


class SchedulePolicies(TypedDict, total=False):
    """Policies controlling overlap, catch-up, and failure behaviour."""

    overlap_policy: ScheduleOverlapPolicy
    catch_up_policy: ScheduleCatchUpPolicy
    catch_up_window: timedelta
    pause_on_failure: bool
    buffer_limit: int      # 0 means unlimited; only meaningful with BUFFER
    concurrency_limit: int  # 0 means unlimited; only meaningful with CONCURRENT


class Schedule(TypedDict, total=False):
    """Complete schedule configuration used for create and update."""

    spec: ScheduleSpec
    action: ScheduleAction
    policies: SchedulePolicies


class Backfill(TypedDict, total=False):
    """Trigger runs for a historical time range.

    ``start_time`` and ``end_time`` are required and must be timezone-aware.
    ``end_time`` must be strictly after ``start_time``.
    ``backfill_id`` defaults to a UUID; the server deduplicates on this ID,
    so retrying with the same value is safe.
    """

    start_time: datetime
    end_time: datetime
    overlap_policy: ScheduleOverlapPolicy
    backfill_id: str


# ---------------------------------------------------------------------------
# Output frozen dataclasses – server-returned state, never mutated by callers.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SchedulePauseInfo:
    """Pause metadata attached to a schedule by the server."""

    reason: str = ""
    paused_at: Optional[datetime] = None
    paused_by: str = ""


@dataclass(frozen=True)
class ScheduleState:
    """Runtime pause state of a schedule."""

    paused: bool = False
    pause_info: Optional[SchedulePauseInfo] = None


@dataclass(frozen=True)
class BackfillInfo:
    """Progress of an ongoing backfill, returned inside ScheduleInfo."""

    backfill_id: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    runs_completed: int = 0
    runs_total: int = 0


@dataclass(frozen=True)
class ScheduleInfo:
    """Runtime information about a schedule returned by the server."""

    last_run_time: Optional[datetime] = None
    next_run_time: Optional[datetime] = None
    total_runs: int = 0
    create_time: Optional[datetime] = None
    last_update_time: Optional[datetime] = None
    ongoing_backfills: tuple[BackfillInfo, ...] = ()


@dataclass(frozen=True)
class ScheduleDescription:
    """Full description of a schedule returned by DescribeSchedule."""

    spec: ScheduleSpec
    action: ScheduleAction
    policies: SchedulePolicies
    state: ScheduleState
    info: ScheduleInfo


@dataclass(frozen=True)
class ScheduleListEntry:
    """Summary entry returned by ListSchedules."""

    schedule_id: str
    workflow_type: str
    state: ScheduleState
    cron_expression: str = ""


# ---------------------------------------------------------------------------
# Semantic error aliases for schedule operations.
# ---------------------------------------------------------------------------

#: Raised when a schedule does not exist (describe / pause / delete / etc.).
ScheduleNotFoundError = EntityNotExistsError

#: Raised by create_schedule() when a schedule with the same ID already exists.
#: Internally, a schedule_id maps to a scheduler workflow ID on the server.
ScheduleAlreadyExistsError = WorkflowExecutionAlreadyStartedError
