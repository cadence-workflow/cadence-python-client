from google.protobuf import timestamp_pb2 as _timestamp_pb2
from cadence.api.v1 import schedule_pb2 as _schedule_pb2
from cadence.api.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union
import datetime

DESCRIPTOR: _descriptor.FileDescriptor

class CreateScheduleRequest(_message.Message):
    __slots__ = ("domain", "schedule_id", "spec", "action", "policies", "memo", "search_attributes")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    SPEC_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    POLICIES_FIELD_NUMBER: _ClassVar[int]
    MEMO_FIELD_NUMBER: _ClassVar[int]
    SEARCH_ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    domain: str
    schedule_id: str
    spec: _schedule_pb2.ScheduleSpec
    action: _schedule_pb2.ScheduleAction
    policies: _schedule_pb2.SchedulePolicies
    memo: _common_pb2.Memo
    search_attributes: _common_pb2.SearchAttributes
    def __init__(self, domain: _Optional[str] = ..., schedule_id: _Optional[str] = ..., spec: _Optional[_Union[_schedule_pb2.ScheduleSpec, _Mapping]] = ..., action: _Optional[_Union[_schedule_pb2.ScheduleAction, _Mapping]] = ..., policies: _Optional[_Union[_schedule_pb2.SchedulePolicies, _Mapping]] = ..., memo: _Optional[_Union[_common_pb2.Memo, _Mapping]] = ..., search_attributes: _Optional[_Union[_common_pb2.SearchAttributes, _Mapping]] = ...) -> None: ...

class CreateScheduleResponse(_message.Message):
    __slots__ = ("schedule_id",)
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    schedule_id: str
    def __init__(self, schedule_id: _Optional[str] = ...) -> None: ...

class DescribeScheduleRequest(_message.Message):
    __slots__ = ("domain", "schedule_id")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    domain: str
    schedule_id: str
    def __init__(self, domain: _Optional[str] = ..., schedule_id: _Optional[str] = ...) -> None: ...

class DescribeScheduleResponse(_message.Message):
    __slots__ = ("spec", "action", "policies", "state", "info", "memo", "search_attributes")
    SPEC_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    POLICIES_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    INFO_FIELD_NUMBER: _ClassVar[int]
    MEMO_FIELD_NUMBER: _ClassVar[int]
    SEARCH_ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    spec: _schedule_pb2.ScheduleSpec
    action: _schedule_pb2.ScheduleAction
    policies: _schedule_pb2.SchedulePolicies
    state: _schedule_pb2.ScheduleState
    info: _schedule_pb2.ScheduleInfo
    memo: _common_pb2.Memo
    search_attributes: _common_pb2.SearchAttributes
    def __init__(self, spec: _Optional[_Union[_schedule_pb2.ScheduleSpec, _Mapping]] = ..., action: _Optional[_Union[_schedule_pb2.ScheduleAction, _Mapping]] = ..., policies: _Optional[_Union[_schedule_pb2.SchedulePolicies, _Mapping]] = ..., state: _Optional[_Union[_schedule_pb2.ScheduleState, _Mapping]] = ..., info: _Optional[_Union[_schedule_pb2.ScheduleInfo, _Mapping]] = ..., memo: _Optional[_Union[_common_pb2.Memo, _Mapping]] = ..., search_attributes: _Optional[_Union[_common_pb2.SearchAttributes, _Mapping]] = ...) -> None: ...

class ListSchedulesRequest(_message.Message):
    __slots__ = ("domain", "page_size", "next_page_token")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    domain: str
    page_size: int
    next_page_token: bytes
    def __init__(self, domain: _Optional[str] = ..., page_size: _Optional[int] = ..., next_page_token: _Optional[bytes] = ...) -> None: ...

class ListSchedulesResponse(_message.Message):
    __slots__ = ("schedules", "next_page_token")
    SCHEDULES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    schedules: _containers.RepeatedCompositeFieldContainer[_schedule_pb2.ScheduleListEntry]
    next_page_token: bytes
    def __init__(self, schedules: _Optional[_Iterable[_Union[_schedule_pb2.ScheduleListEntry, _Mapping]]] = ..., next_page_token: _Optional[bytes] = ...) -> None: ...

class DeleteScheduleRequest(_message.Message):
    __slots__ = ("domain", "schedule_id")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    domain: str
    schedule_id: str
    def __init__(self, domain: _Optional[str] = ..., schedule_id: _Optional[str] = ...) -> None: ...

class DeleteScheduleResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class PauseScheduleRequest(_message.Message):
    __slots__ = ("domain", "schedule_id", "reason", "identity")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    domain: str
    schedule_id: str
    reason: str
    identity: str
    def __init__(self, domain: _Optional[str] = ..., schedule_id: _Optional[str] = ..., reason: _Optional[str] = ..., identity: _Optional[str] = ...) -> None: ...

class PauseScheduleResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class UnpauseScheduleRequest(_message.Message):
    __slots__ = ("domain", "schedule_id", "reason", "catch_up_policy")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    CATCH_UP_POLICY_FIELD_NUMBER: _ClassVar[int]
    domain: str
    schedule_id: str
    reason: str
    catch_up_policy: _schedule_pb2.ScheduleCatchUpPolicy
    def __init__(self, domain: _Optional[str] = ..., schedule_id: _Optional[str] = ..., reason: _Optional[str] = ..., catch_up_policy: _Optional[_Union[_schedule_pb2.ScheduleCatchUpPolicy, str]] = ...) -> None: ...

class UnpauseScheduleResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class BackfillScheduleRequest(_message.Message):
    __slots__ = ("domain", "schedule_id", "start_time", "end_time", "overlap_policy", "backfill_id")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    OVERLAP_POLICY_FIELD_NUMBER: _ClassVar[int]
    BACKFILL_ID_FIELD_NUMBER: _ClassVar[int]
    domain: str
    schedule_id: str
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    overlap_policy: _schedule_pb2.ScheduleOverlapPolicy
    backfill_id: str
    def __init__(self, domain: _Optional[str] = ..., schedule_id: _Optional[str] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., overlap_policy: _Optional[_Union[_schedule_pb2.ScheduleOverlapPolicy, str]] = ..., backfill_id: _Optional[str] = ...) -> None: ...

class BackfillScheduleResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class UpdateScheduleRequest(_message.Message):
    __slots__ = ("domain", "schedule_id", "spec", "action", "policies", "search_attributes")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SCHEDULE_ID_FIELD_NUMBER: _ClassVar[int]
    SPEC_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    POLICIES_FIELD_NUMBER: _ClassVar[int]
    SEARCH_ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    domain: str
    schedule_id: str
    spec: _schedule_pb2.ScheduleSpec
    action: _schedule_pb2.ScheduleAction
    policies: _schedule_pb2.SchedulePolicies
    search_attributes: _common_pb2.SearchAttributes
    def __init__(self, domain: _Optional[str] = ..., schedule_id: _Optional[str] = ..., spec: _Optional[_Union[_schedule_pb2.ScheduleSpec, _Mapping]] = ..., action: _Optional[_Union[_schedule_pb2.ScheduleAction, _Mapping]] = ..., policies: _Optional[_Union[_schedule_pb2.SchedulePolicies, _Mapping]] = ..., search_attributes: _Optional[_Union[_common_pb2.SearchAttributes, _Mapping]] = ...) -> None: ...

class UpdateScheduleResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
