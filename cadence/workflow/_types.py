from datetime import datetime, timedelta
from typing import (
    Any,
    Awaitable,
    Generator,
    Protocol,
    TypeVar,
    TypedDict,
    Union,
    runtime_checkable,
)

from cadence.api.v1 import workflow_pb2

ResultType = TypeVar("ResultType")
ResultType_co = TypeVar("ResultType_co", covariant=True)
SearchAttributeType = str | int | float | bool | datetime
DEFAULT_VERSION = -1
CADENCE_CHANGE_VERSION_SEARCH_ATTRIBUTE = "CadenceChangeVersion"


class RetryPolicy(TypedDict, total=False):
    initial_interval: timedelta | None
    backoff_coefficient: float | None
    maximum_interval: timedelta | None
    maximum_attempts: int | None
    non_retryable_error_reasons: list[str] | None
    expiration_interval: timedelta | None


class ClusterAttribute(TypedDict, total=False):
    scope: str
    name: str


class ActiveClusterSelectionPolicy(TypedDict, total=False):
    cluster_attribute: ClusterAttribute


class ActivityOptions(TypedDict, total=False):
    task_list: str
    schedule_to_close_timeout: timedelta
    schedule_to_start_timeout: timedelta
    start_to_close_timeout: timedelta
    heartbeat_timeout: timedelta
    retry_policy: RetryPolicy


class ChildWorkflowOptions(TypedDict, total=False):
    workflow_id: str
    domain: str
    task_list: str
    execution_start_to_close_timeout: timedelta
    task_start_to_close_timeout: timedelta
    parent_close_policy: Union[workflow_pb2.ParentClosePolicy, str]
    workflow_id_reuse_policy: Union[workflow_pb2.WorkflowIdReusePolicy, str]
    retry_policy: RetryPolicy
    cron_schedule: str
    memo: dict[str, Any]


@runtime_checkable
class ChildWorkflowFuture(Awaitable[ResultType_co], Protocol[ResultType_co]):
    """Handle to a started child workflow, awaitable for its result."""

    @property
    def workflow_id(self) -> str: ...

    @property
    def run_id(self) -> str: ...

    def cancel(self) -> bool:
        """Request cancellation of the child workflow."""
        ...

    async def signal(self, signal_name: str, *args: Any) -> None:
        """Send a signal to this child workflow."""
        ...

    def __await__(self) -> Generator[Any, None, ResultType_co]: ...
