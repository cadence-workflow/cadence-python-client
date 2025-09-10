from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta, datetime
from typing import Iterator

from cadence import Client


@dataclass(frozen=True)
class ActivityInfo:
    task_token: bytes
    workflow_type: str
    workflow_domain: str
    workflow_id: str
    workflow_run_id: str
    activity_id: str
    activity_type: str
    task_list: str
    heartbeat_timeout: timedelta
    scheduled_timestamp: datetime
    started_timestamp: datetime
    start_to_close_timeout: timedelta
    attempt: int

def client() -> Client:
    return ActivityContext.get().client()

def in_activity() -> bool:
    return ActivityContext.is_set()

def info() -> ActivityInfo:
    return ActivityContext.get().info()



class ActivityContext(ABC):
    _var: ContextVar['ActivityContext'] = ContextVar("activity")

    @abstractmethod
    def info(self) -> ActivityInfo:
        ...

    @abstractmethod
    def client(self) -> Client:
        ...

    @contextmanager
    def _activate(self) -> Iterator[None]:
        token = ActivityContext._var.set(self)
        yield None
        ActivityContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return ActivityContext._var.get(None) is not None

    @staticmethod
    def get() -> 'ActivityContext':
        return ActivityContext._var.get()
