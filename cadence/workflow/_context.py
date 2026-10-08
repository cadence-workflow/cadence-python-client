from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from typing import (
    Any,
    Callable,
    Iterator,
    Mapping,
    Type,
    Unpack,
)

from cadence.data_converter import DataConverter
from cadence.workflow._types import (
    ActivityOptions,
    ChildWorkflowFuture,
    ChildWorkflowOptions,
    ResultType,
    SearchAttributeType,
)


@dataclass(frozen=True)
class WorkflowCancellationInfo:
    cause: str
    identity: str
    request_id: str


@dataclass(frozen=True)
class WorkflowInfo:
    workflow_type: str
    workflow_domain: str
    workflow_id: str
    workflow_run_id: str
    workflow_task_list: str
    data_converter: DataConverter
    memo: dict[str, Any] | None = None
    search_attributes: (
        dict[str, SearchAttributeType | list[SearchAttributeType]] | None
    ) = None


class WorkflowContext(ABC):
    _var: ContextVar["WorkflowContext"] = ContextVar("workflow")

    @abstractmethod
    def info(self) -> WorkflowInfo: ...

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

    @abstractmethod
    async def execute_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> ResultType: ...

    @abstractmethod
    async def start_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> "ChildWorkflowFuture[ResultType]": ...

    @abstractmethod
    async def signal_child_workflow(
        self,
        child_workflow_id: str,
        signal_name: str,
        *args: Any,
    ) -> None: ...

    @abstractmethod
    async def signal_external_workflow(
        self,
        workflow_id: str,
        signal_name: str,
        *args: Any,
        run_id: str = "",
        domain: str = "",
    ) -> None: ...

    @abstractmethod
    async def start_timer(self, duration: timedelta) -> None: ...

    @abstractmethod
    async def wait_condition(self, predicate: Callable[[], bool]) -> None: ...

    @abstractmethod
    def side_effect(
        self,
        fn: Callable[[], ResultType],
        result_type: Type[ResultType],
    ) -> ResultType: ...

    @abstractmethod
    def mutable_side_effect(
        self,
        id: str,
        fn: Callable[[], ResultType],
        result_type: Type[ResultType],
        updated: Callable[[ResultType, ResultType], bool],
    ) -> ResultType: ...

    @abstractmethod
    def get_version(
        self,
        change_id: str,
        min_supported: int,
        max_supported: int,
    ) -> int: ...

    @abstractmethod
    def upsert_search_attributes(
        self, attributes: Mapping[str, SearchAttributeType | list[SearchAttributeType]]
    ) -> None: ...

    @abstractmethod
    def is_cancel_requested(self) -> bool: ...

    def inject_propagated_headers(self) -> dict[str, bytes]:
        """Return headers to attach to outbound workflow decisions."""
        return {}

    @contextmanager
    def _activate(self) -> Iterator["WorkflowContext"]:
        token = WorkflowContext._var.set(self)
        try:
            yield self
        finally:
            WorkflowContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return WorkflowContext._var.get(None) is not None

    @staticmethod
    def get() -> "WorkflowContext":
        res = WorkflowContext._var.get(None)
        if res is None:
            raise RuntimeError("Workflow function used outside of workflow context")
        return res
