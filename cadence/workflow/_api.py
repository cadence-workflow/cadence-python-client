from datetime import timedelta
from typing import (
    Any,
    Callable,
    Mapping,
    NoReturn,
    Type,
    Unpack,
)

from cadence.error import ContinueAsNewError
from cadence.workflow._context import WorkflowContext
from cadence.workflow._types import (
    CADENCE_CHANGE_VERSION_SEARCH_ATTRIBUTE,
    ActivityOptions,
    ChildWorkflowFuture,
    ChildWorkflowOptions,
    ResultType,
    SearchAttributeType,
)


async def execute_activity(
    activity: str,
    result_type: Type[ResultType],
    *args: Any,
    **kwargs: Unpack[ActivityOptions],
) -> ResultType:
    return await WorkflowContext.get().execute_activity(
        activity, result_type, *args, **kwargs
    )


async def execute_child_workflow(
    workflow_type: str,
    result_type: Type[ResultType],
    *args: Any,
    **kwargs: Unpack[ChildWorkflowOptions],
) -> ResultType:
    return await WorkflowContext.get().execute_child_workflow(
        workflow_type, result_type, *args, **kwargs
    )


async def start_child_workflow(
    workflow_type: str,
    result_type: Type[ResultType],
    *args: Any,
    **kwargs: Unpack[ChildWorkflowOptions],
) -> "ChildWorkflowFuture[ResultType]":
    return await WorkflowContext.get().start_child_workflow(
        workflow_type, result_type, *args, **kwargs
    )


async def signal_external_workflow(
    workflow_id: str,
    signal_name: str,
    *args: Any,
    run_id: str = "",
    domain: str = "",
) -> None:
    """Send a signal to an external workflow execution.

    Args:
        workflow_id: Target workflow ID.
        signal_name: Name of the signal to deliver.
        *args: Signal payload arguments, serialized via DataConverter.
        run_id: Target run ID. Empty string targets the currently running execution.
        domain: Target domain. Empty string defaults to the current workflow's domain.
    """
    await WorkflowContext.get().signal_external_workflow(
        workflow_id, signal_name, *args, run_id=run_id, domain=domain
    )


async def sleep(duration: timedelta) -> None:
    return await WorkflowContext.get().start_timer(duration)


async def wait_condition(predicate: Callable[[], bool]) -> None:
    """Block until predicate returns True.

    The predicate is re-evaluated after any workflow state change
    (signal delivery, activity completion, timer firing).
    If the predicate is already True, returns immediately.
    """
    await WorkflowContext.get().wait_condition(predicate)


def side_effect(
    fn: Callable[[], ResultType],
    result_type: Type[ResultType],
) -> ResultType:
    """Execute non-deterministic code and record the result as a SideEffect marker.

    On replay the function is not called; the value from workflow history is returned.
    """
    return WorkflowContext.get().side_effect(fn, result_type)


def mutable_side_effect(
    id: str,
    fn: Callable[[], ResultType],
    result_type: Type[ResultType],
    updated: Callable[[ResultType, ResultType], bool],
) -> ResultType:
    """Return a non-deterministic value, recording it only when it changes.

    ``id`` must remain stable for the workflow execution. ``updated`` receives
    the previously recorded value and the new value, and returns whether the new
    value should be persisted. During replay, neither callback is invoked.
    """
    return WorkflowContext.get().mutable_side_effect(id, fn, result_type, updated)


def get_version(
    change_id: str,
    min_supported: int,
    max_supported: int,
) -> int:
    """Return the deterministic version for ``change_id``.

    A new execution selects ``max_supported`` and records it when it is not
    ``DEFAULT_VERSION``. It also updates the reserved ``CadenceChangeVersion``
    search attribute so executions can be queried by ``"<change_id>-<version>"``.
    A recorded marker is the source of truth for subsequent calls. When replaying
    history from before this marker was introduced, the result is
    ``DEFAULT_VERSION``; therefore ``min_supported`` must include
    ``DEFAULT_VERSION`` until those executions have completed.

    """
    return WorkflowContext.get().get_version(change_id, min_supported, max_supported)


def upsert_search_attributes(
    attributes: Mapping[str, SearchAttributeType | list[SearchAttributeType]],
) -> None:
    """Add or update indexed search attributes for this workflow execution.

    Keys and value types must be registered on the Cadence server (see
    GetSearchAttributes). Values may be a scalar (str, int, float, bool,
    datetime) or a list of that scalar type. Values are merged into the
    existing map; there is no API to remove a key. ``CadenceChangeVersion`` is
    reserved for :func:`get_version`. During replay this is a no-op aside from
    updating :attr:`WorkflowInfo.search_attributes`.
    """
    if CADENCE_CHANGE_VERSION_SEARCH_ATTRIBUTE in attributes:
        raise ValueError(
            f"{CADENCE_CHANGE_VERSION_SEARCH_ATTRIBUTE} is reserved for "
            "workflow versioning"
        )
    WorkflowContext.get().upsert_search_attributes(attributes)


def is_cancel_requested() -> bool:
    return WorkflowContext.get().is_cancel_requested()


def continue_as_new(
    *args: Any,
    workflow_type: str | None = None,
    task_list: str | None = None,
    execution_start_to_close_timeout: timedelta | None = None,
    task_start_to_close_timeout: timedelta | None = None,
) -> NoReturn:
    """Continue this workflow as a new execution.

    This function never returns. It raises ContinueAsNewError which
    propagates out of the workflow to signal the worker to create a
    continue-as-new decision.

    This is different from go sdk

    Args:
        *args: Arguments for the new workflow execution.
        workflow_type: Override workflow type (default: same type).
        task_list: Override task list (default: same task list).
        execution_start_to_close_timeout: Override execution timeout.
        task_start_to_close_timeout: Override task timeout.
    """
    raise ContinueAsNewError(
        *args,
        workflow_type=workflow_type,
        task_list=task_list,
        execution_start_to_close_timeout=execution_start_to_close_timeout,
        task_start_to_close_timeout=task_start_to_close_timeout,
        headers=WorkflowContext.get().inject_propagated_headers(),
    )
