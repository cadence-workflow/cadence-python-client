from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from cadence.api.v1 import common_pb2 as _common_pb2
from cadence.api.v1 import tasklist_pb2 as _tasklist_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union
import datetime

DESCRIPTOR: _descriptor.FileDescriptor

class ScheduleOverlapPolicy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SCHEDULE_OVERLAP_POLICY_INVALID: _ClassVar[ScheduleOverlapPolicy]
    SCHEDULE_OVERLAP_POLICY_SKIP_NEW: _ClassVar[ScheduleOverlapPolicy]
    SCHEDULE_OVERLAP_POLICY_BUFFER: _ClassVar[ScheduleOverlapPolicy]
    SCHEDULE_OVERLAP_POLICY_CONCURRENT: _ClassVar[ScheduleOverlapPolicy]
    SCHEDULE_OVERLAP_POLICY_CANCEL_PREVIOUS: _ClassVar[ScheduleOverlapPolicy]
    SCHEDULE_OVERLAP_POLICY_TERMINATE_PREVIOUS: _ClassVar[ScheduleOverlapPolicy]

class ScheduleCatchUpPolicy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SCHEDULE_CATCH_UP_POLICY_INVALID: _ClassVar[ScheduleCatchUpPolicy]
    SCHEDULE_CATCH_UP_POLICY_SKIP: _ClassVar[ScheduleCatchUpPolicy]
    SCHEDULE_CATCH_UP_POLICY_ONE: _ClassVar[ScheduleCatchUpPolicy]
    SCHEDULE_CATCH_UP_POLICY_ALL: _ClassVar[ScheduleCatchUpPolicy]
SCHEDULE_OVERLAP_POLICY_INVALID: ScheduleOverlapPolicy
SCHEDULE_OVERLAP_POLICY_SKIP_NEW: ScheduleOverlapPolicy
SCHEDULE_OVERLAP_POLICY_BUFFER: ScheduleOverlapPolicy
SCHEDULE_OVERLAP_POLICY_CONCURRENT: ScheduleOverlapPolicy
SCHEDULE_OVERLAP_POLICY_CANCEL_PREVIOUS: ScheduleOverlapPolicy
SCHEDULE_OVERLAP_POLICY_TERMINATE_PREVIOUS: ScheduleOverlapPolicy
SCHEDULE_CATCH_UP_POLICY_INVALID: ScheduleCatchUpPolicy
SCHEDULE_CATCH_UP_POLICY_SKIP: ScheduleCatchUpPolicy
SCHEDULE_CATCH_UP_POLICY_ONE: ScheduleCatchUpPolicy
SCHEDULE_CATCH_UP_POLICY_ALL: ScheduleCatchUpPolicy

class ScheduleSpec(_message.Message):
    __slots__ = ("cron_expression", "start_time", "end_time", "jitter")
    CRON_EXPRESSION_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    JITTER_FIELD_NUMBER: _ClassVar[int]
    cron_expression: str
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    jitter: _duration_pb2.Duration
    def __init__(self, cron_expression: _Optional[str] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., jitter: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class ScheduleAction(_message.Message):
    __slots__ = ("start_workflow",)
    class StartWorkflowAction(_message.Message):
        __slots__ = ("workflow_type", "task_list", "input", "workflow_id_prefix", "execution_start_to_close_timeout", "task_start_to_close_timeout", "retry_policy", "memo", "search_attributes")
        WORKFLOW_TYPE_FIELD_NUMBER: _ClassVar[int]
        TASK_LIST_FIELD_NUMBER: _ClassVar[int]
        INPUT_FIELD_NUMBER: _ClassVar[int]
        WORKFLOW_ID_PREFIX_FIELD_NUMBER: _ClassVar[int]
        EXECUTION_START_TO_CLOSE_TIMEOUT_FIELD_NUMBER: _ClassVar[int]
        TASK_START_TO_CLOSE_TIMEOUT_FIELD_NUMBER: _ClassVar[int]
        RETRY_POLICY_FIELD_NUMBER: _ClassVar[int]
        MEMO_FIELD_NUMBER: _ClassVar[int]
        SEARCH_ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
        workflow_type: _common_pb2.WorkflowType
        task_list: _tasklist_pb2.TaskList
        input: _common_pb2.Payload
        workflow_id_prefix: str
        execution_start_to_close_timeout: _duration_pb2.Duration
        task_start_to_close_timeout: _duration_pb2.Duration
        retry_policy: _common_pb2.RetryPolicy
        memo: _common_pb2.Memo
        search_attributes: _common_pb2.SearchAttributes
        def __init__(self, workflow_type: _Optional[_Union[_common_pb2.WorkflowType, _Mapping]] = ..., task_list: _Optional[_Union[_tasklist_pb2.TaskList, _Mapping]] = ..., input: _Optional[_Union[_common_pb2.Payload, _Mapping]] = ..., workflow_id_prefix: _Optional[str] = ..., execution_start_to_close_timeout: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., task_start_to_close_timeout: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., retry_policy: _Optional[_Union[_common_pb2.RetryPolicy, _Mapping]] = ..., memo: _Optional[_Union[_common_pb2.Memo, _Mapping]] = ..., search_attributes: _Optional[_Union[_common_pb2.SearchAttributes, _Mapping]] = ...) -> None: ...
    START_WORKFLOW_FIELD_NUMBER: _ClassVar[int]
    start_workflow: ScheduleAction.StartWorkflowAction
    def __init__(self, start_workflow: _Optional[_Union[ScheduleAction.StartWorkflowAction, _Mapping]] = ...) -> None: ...

class SchedulePolicies(_message.Message):
    __slots__ = ("overlap_policy", "catch_up_policy", "catch_up_window", "pause_on_failure", "buffer_limit", "concurrency_limit")
    OVERLAP_POLICY_FIELD_NUMBER: _ClassVar[int]
    CATCH_UP_POLICY_FIELD_NUMBER: _ClassVar[int]
    CATCH_UP_WINDOW_FIELD_NUMBER: _ClassVar[int]
    PAUSE_ON_FAILURE_FIELD_NUMBER: _ClassVar[int]
    BUFFER_LIMIT_FIELD_NUMBER: _ClassVar[int]
    CONCURRENCY_LIMIT_FIELD_NUMBER: _ClassVar[int]
    overlap_policy: ScheduleOverlapPolicy
    catch_up_policy: ScheduleCatchUpPolicy
    catch_up_window: _duration_pb2.Duration
    pause_on_failure: bool
    buffer_limit: int
    concurrency_limit: int
    def __init__(self, overlap_policy: _Optional[_Union[ScheduleOverlapPolicy, str]] = ..., catch_up_policy: _Optional[_Union[ScheduleCatchUpPolicy, str]] = ..., catch_up_window: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., pause_on_failure: bool = ..., buffer_limit: _Optional[int] = ..., concurrency_limit: _Optional[int] = ...) -> None: ...

class SchedulePauseInfo(_message.Message):
    __slots__ = ("reason", "paused_at", "paused_by")
    REASON_FIELD_NUMBER: _ClassVar[int]
    PAUSED_AT_FIELD_NUMBER: _ClassVar[int]
    PAUSED_BY_FIELD_NUMBER: _ClassVar[int]
    reason: str
    paused_at: _timestamp_pb2.Timestamp
    paused_by: str
    def __init__(self, reason: _Optional[str] = ..., paused_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., paused_by: _Optional[str] = ...) -> None: ...

class ScheduleState(_message.Message):
    __slots__ = ("paused", "pause_info")
    PAUSED_FIELD_NUMBER: _ClassVar[int]
    PAUSE_INFO_FIELD_NUMBER: _ClassVar[int]
    paused: bool
    pause_info: SchedulePauseInfo
    def __init__(self, paused: bool = ..., pause_info: _Optional[_Union[SchedulePauseInfo, _Mapping]] = ...) -> None: ...

class BackfillInfo(_message.Message):
    __slots__ = ("backfill_id", "start_time", "end_time", "runs_completed", "runs_total")
    BACKFILL_ID_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    RUNS_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    RUNS_TOTAL_FIELD_NUMBER: _ClassVar[int]
    backfill_id: str
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    runs_completed: int
    runs_total: int
    def __init__(self, backfill_id: _Optional[str] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., runs_completed: _Optional[int] = ..., runs_total: _Optional[int] = ...) -> None: ...

class ScheduleInfo(_message.Message):
    __slots__ = ("last_run_time", "next_run_time", "total_runs", "create_time", "last_update_time", "ongoing_backfills")
    LAST_RUN_TIME_FIELD_NUMBER: _ClassVar[int]
    NEXT_RUN_TIME_FIELD_NUMBER: _ClassVar[int]
    TOTAL_RUNS_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    LAST_UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
    ONGOING_BACKFILLS_FIELD_NUMBER: _ClassVar[int]
    last_run_time: _timestamp_pb2.Timestamp
    next_run_time: _timestamp_pb2.Timestamp
    total_runs: int
    create_time: _timestamp_pb2.Timestamp
    last_update_time: _timestamp_pb2.Timestamp
    ongoing_backfills: _containers.RepeatedCompositeFieldContainer[BackfillInfo]
    def __init__(self, last_run_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., next_run_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., total_runs: _Optional[int] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., last_update_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., ongoing_backfills: _Optional[_Iterable[_Union[BackfillInfo, _Mapping]]] = ...) -> None: ...

class ScheduleListEntry(_message.Message):
    __slots__ = ("schedule_id", "workflow_type", "state", "cron_expression")
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    WORKFLOW_TYPE_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    CRON_EXPRESSION_FIELD_NUMBER: _ClassVar[int]
    schedule_id: str
    workflow_type: _common_pb2.WorkflowType
    state: ScheduleState
    cron_expression: str
    def __init__(self, schedule_id: _Optional[str] = ..., workflow_type: _Optional[_Union[_common_pb2.WorkflowType, _Mapping]] = ..., state: _Optional[_Union[ScheduleState, _Mapping]] = ..., cron_expression: _Optional[str] = ...) -> None: ...
