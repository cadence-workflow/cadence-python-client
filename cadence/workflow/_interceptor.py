from datetime import timedelta
from typing import Any, Callable, Mapping, Type, TypeAlias, Unpack

from typing_extensions import override

from cadence.data_converter import DataConverter
from cadence.workflow._context import WorkflowContext, WorkflowInfo
from cadence.workflow._types import (
    ActivityOptions,
    ChildWorkflowFuture,
    ChildWorkflowOptions,
    ResultType,
    SearchAttributeType,
)


class WorkflowInterceptor(WorkflowContext):
    """Base class for intercepting WorkflowContext calls.

    Every method forwards to the delegate unchanged. Subclasses override the
    methods they care about and call ``super()`` (optionally with rewritten
    arguments) to continue down the chain.
    """

    def __init__(self, delegate: WorkflowContext) -> None:
        self._delegate = delegate

    @override
    def info(self) -> WorkflowInfo:
        return self._delegate.info()

    @override
    def data_converter(self) -> DataConverter:
        return self._delegate.data_converter()

    @override
    async def execute_activity(
        self,
        activity: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ActivityOptions],
    ) -> ResultType:
        return await self._delegate.execute_activity(
            activity, result_type, *args, **kwargs
        )

    @override
    async def execute_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> ResultType:
        return await self._delegate.execute_child_workflow(
            workflow_type, result_type, *args, **kwargs
        )

    @override
    async def start_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> "ChildWorkflowFuture[ResultType]":
        return await self._delegate.start_child_workflow(
            workflow_type, result_type, *args, **kwargs
        )

    @override
    async def signal_child_workflow(
        self,
        child_workflow_id: str,
        signal_name: str,
        *args: Any,
    ) -> None:
        await self._delegate.signal_child_workflow(
            child_workflow_id, signal_name, *args
        )

    @override
    async def signal_external_workflow(
        self,
        workflow_id: str,
        signal_name: str,
        *args: Any,
        run_id: str = "",
        domain: str = "",
    ) -> None:
        await self._delegate.signal_external_workflow(
            workflow_id, signal_name, *args, run_id=run_id, domain=domain
        )

    @override
    async def start_timer(self, duration: timedelta) -> None:
        await self._delegate.start_timer(duration)

    @override
    async def wait_condition(self, predicate: Callable[[], bool]) -> None:
        await self._delegate.wait_condition(predicate)

    @override
    def side_effect(
        self,
        fn: Callable[[], ResultType],
        result_type: Type[ResultType],
    ) -> ResultType:
        return self._delegate.side_effect(fn, result_type)

    @override
    def mutable_side_effect(
        self,
        id: str,
        fn: Callable[[], ResultType],
        result_type: Type[ResultType],
        updated: Callable[[ResultType, ResultType], bool],
    ) -> ResultType:
        return self._delegate.mutable_side_effect(id, fn, result_type, updated)

    @override
    def get_version(
        self,
        change_id: str,
        min_supported: int,
        max_supported: int,
    ) -> int:
        return self._delegate.get_version(change_id, min_supported, max_supported)

    @override
    def upsert_search_attributes(
        self, attributes: Mapping[str, SearchAttributeType | list[SearchAttributeType]]
    ) -> None:
        self._delegate.upsert_search_attributes(attributes)

    @override
    def is_cancel_requested(self) -> bool:
        return self._delegate.is_cancel_requested()

    @override
    def inject_propagated_headers(self) -> dict[str, bytes]:
        return self._delegate.inject_propagated_headers()


WorkflowInterceptorFactory: TypeAlias = Callable[[WorkflowContext], WorkflowContext]
"""Wraps the WorkflowContext of each workflow execution, typically in one or
more WorkflowInterceptor instances, e.g. ``lambda ctx: Tracing(Logging(ctx))``.
"""
