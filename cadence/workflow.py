from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator, TypedDict, TypeVar, Type, Unpack, Any

from cadence.client import Client
from cadence.data_converter import DataConverter

ResultType = TypeVar("ResultType")


class ActivityOptions(TypedDict, total=False):
    task_list: str
    schedule_to_close_timeout: timedelta
    schedule_to_start_timeout: timedelta
    start_to_close_timeout: timedelta
    heartbeat_timeout: timedelta


async def execute_activity(
    activity: str,
    result_type: Type[ResultType],
    *args: Any,
    **kwargs: Unpack[ActivityOptions],
) -> ResultType:
    return await WorkflowContext.get().execute_activity(
        activity, result_type, *args, **kwargs
    )


@dataclass
class WorkflowInfo:
    workflow_type: str
    workflow_domain: str
    workflow_id: str
    workflow_run_id: str
    workflow_task_list: str


class WorkflowContext(ABC):
    _var: ContextVar["WorkflowContext"] = ContextVar("workflow")

    @abstractmethod
    def info(self) -> WorkflowInfo: ...

    @abstractmethod
    def client(self) -> Client: ...

    @abstractmethod
    def data_converter(self) -> DataConverter: ...

    @abstractmethod
    async def execute_activity(
        self,
        activity: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ActivityOptions],
    ) -> ResultType: ...

    @contextmanager
    def _activate(self) -> Iterator[None]:
        token = WorkflowContext._var.set(self)
        yield None
        WorkflowContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return WorkflowContext._var.get(None) is not None

    @staticmethod
    def get() -> "WorkflowContext":
        return WorkflowContext._var.get()
