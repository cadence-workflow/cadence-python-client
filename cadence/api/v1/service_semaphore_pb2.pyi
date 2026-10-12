from cadence.api.v1 import semaphore_pb2 as _semaphore_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CreateSemaphoreRequest(_message.Message):
    __slots__ = ("domain", "semaphore_name", "capacity", "bucket_capacity")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SEMAPHORE_NAME_FIELD_NUMBER: _ClassVar[int]
    CAPACITY_FIELD_NUMBER: _ClassVar[int]
    BUCKET_CAPACITY_FIELD_NUMBER: _ClassVar[int]
    domain: str
    semaphore_name: str
    capacity: int
    bucket_capacity: int
    def __init__(self, domain: _Optional[str] = ..., semaphore_name: _Optional[str] = ..., capacity: _Optional[int] = ..., bucket_capacity: _Optional[int] = ...) -> None: ...

class CreateSemaphoreResponse(_message.Message):
    __slots__ = ("semaphore",)
    SEMAPHORE_FIELD_NUMBER: _ClassVar[int]
    semaphore: _semaphore_pb2.Semaphore
    def __init__(self, semaphore: _Optional[_Union[_semaphore_pb2.Semaphore, _Mapping]] = ...) -> None: ...
