from datetime import timedelta

import pytest

from cadence import Registry, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryResponse,
    GetWorkflowExecutionHistoryRequest,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

reg = Registry()


@reg.workflow()
class EchoWorkflow:
    def __init__(self):
        pass

    @workflow.run
    async def echo(self, message: str) -> str:
        return message


async def test_simple_workflow(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "EchoWorkflow",
            "hello world",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        assert (
            '"hello world"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


@pytest.mark.skip(reason="Incorrect WorkflowType")
async def test_workflow_fn(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            EchoWorkflow.echo,
            "hello world",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        assert (
            '"hello world"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )
