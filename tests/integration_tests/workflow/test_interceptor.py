from datetime import timedelta
from typing import Any, Mapping, Type, Unpack

from cadence import Registry, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from cadence.workflow import (
    ActivityOptions,
    ChildWorkflowOptions,
    ResultType,
    SearchAttributeType,
    WorkflowContext,
    WorkflowInterceptor,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()


@registry.activity()
async def echo(message: str) -> str:
    return message


@registry.workflow()
class InterceptedChildWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        return f"child:{message}"


@registry.workflow()
class InterceptedParentWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        activity_result = await echo.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute(message)

        run_id = WorkflowContext.get().info().workflow_run_id
        child_result = await workflow.execute_child_workflow(
            "InterceptedChildWorkflow",
            str,
            message,
            workflow_id=f"{run_id}-child",
            execution_start_to_close_timeout=timedelta(seconds=30),
            task_start_to_close_timeout=timedelta(seconds=10),
        )

        workflow.upsert_search_attributes({"CustomKeywordField": "original"})
        return f"{activity_result}|{child_result}"


def _rewrite(args: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(f"intercepted-{a}" if isinstance(a, str) else a for a in args)


class RewritingInterceptor(WorkflowInterceptor):
    async def execute_activity(
        self,
        activity: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ActivityOptions],
    ) -> ResultType:
        return await super().execute_activity(
            activity, result_type, *_rewrite(args), **kwargs
        )

    async def execute_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> ResultType:
        return await super().execute_child_workflow(
            workflow_type, result_type, *_rewrite(args), **kwargs
        )

    def upsert_search_attributes(
        self, attributes: Mapping[str, SearchAttributeType | list[SearchAttributeType]]
    ) -> None:
        super().upsert_search_attributes({"CustomKeywordField": "intercepted"})


async def test_interceptor_rewrites_workflow_operations(helper: CadenceHelper):
    intercepting_helper = CadenceHelper(
        {**helper.options, "workflow_interceptor_factory": RewritingInterceptor},
        helper.test_name,
        helper.fspath,
    )
    async with intercepting_helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "InterceptedParentWorkflow",
            "hello",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        close: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )
        full: GetWorkflowExecutionHistoryResponse = (
            await worker.client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=DOMAIN_NAME,
                    workflow_execution=execution,
                    skip_archival=True,
                )
            )
        )

    # Both the activity and the child workflow received the rewritten argument.
    assert (
        close.history.events[
            -1
        ].workflow_execution_completed_event_attributes.result.data
        == b'"intercepted-hello|child:intercepted-hello"'
    )

    upserts = [
        e.upsert_workflow_search_attributes_event_attributes
        for e in full.history.events
        if e.HasField("upsert_workflow_search_attributes_event_attributes")
    ]
    assert len(upserts) == 1
    assert (
        upserts[0].search_attributes.indexed_fields["CustomKeywordField"].data
        == b'"intercepted"'
    )
