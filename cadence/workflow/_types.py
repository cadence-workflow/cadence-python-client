from asyncio import Future
from datetime import datetime, timedelta
from typing import (
    Any,
    TypeVar,
    TypedDict,
    Union,
)

from cadence.api.v1 import workflow_pb2
from cadence.api.v1.common_pb2 import WorkflowExecution

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


# See https://github.com/python/typeshed/pull/8781 .
# Future objects in Python are mutable, so their type parameter is invariant. You can't replace Future[any] with Future[str].
# We however operate on covariant types, because our typing comes from user functions.
# Functions are always covariant because a function that returns type any is always allowed to return subclass str.
# As a result, we need a new type that accepts a covariant type parameter rather than using Future directly.
# asyncio already does this with the Task type, but our Futures aren't tasks.
# Python's current typing doesn't have a way to express this, so we end up with an ignore to allow it.
class WorkflowFuture(Future[ResultType_co]):  # type: ignore[type-var]
    """Futures returned as part of a Workflow.

    They may be canceled, but they cannot be mutated(set_result, set_exception) as they reflect an external asynchronous
    operation. Workflow code can freely use normal asyncio Futures.
    """


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


class ChildWorkflowFuture(WorkflowFuture[ResultType_co]):
    """Handle to a child workflow. Resolves to the child's result.

    Cancelling the future requests cancellation of the child workflow.
    """

    @property
    def workflow_id(self) -> str:
        raise NotImplementedError

    @property
    def execution(self) -> WorkflowFuture[WorkflowExecution]:
        """Resolves once the child has started, or raises if it failed to start."""
        raise NotImplementedError

    @property
    def run_id(self) -> str:
        """Run ID of the child. Only available once :attr:`execution` is done."""
        return self.execution.result().run_id

    def signal(self, signal_name: str, *args: Any) -> WorkflowFuture[None]:
        """Send a signal to this child workflow."""
        raise NotImplementedError
