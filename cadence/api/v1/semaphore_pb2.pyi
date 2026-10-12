from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Semaphore(_message.Message):
    __slots__ = ("semaphore_name", "capacity", "bucket_capacity")
    SEMAPHORE_NAME_FIELD_NUMBER: _ClassVar[int]
    CAPACITY_FIELD_NUMBER: _ClassVar[int]
    BUCKET_CAPACITY_FIELD_NUMBER: _ClassVar[int]
    semaphore_name: str
    capacity: int
    bucket_capacity: int
    def __init__(self, semaphore_name: _Optional[str] = ..., capacity: _Optional[int] = ..., bucket_capacity: _Optional[int] = ...) -> None: ...
