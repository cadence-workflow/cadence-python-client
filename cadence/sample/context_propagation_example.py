"""Run a ContextVar propagation example against a Cadence server."""

import asyncio
import os
from contextvars import ContextVar
from datetime import timedelta

from cadence import Client, ContextVarPropagator, workflow
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import GetWorkflowExecutionHistoryRequest
from cadence.worker import Registry, Worker

REQUEST_ID: ContextVar[str] = ContextVar("request_id")
REQUEST_ID_PROPAGATOR = ContextVarPropagator(
    REQUEST_ID,
    "request-id",
    lambda value: value.encode(),
    bytes.decode,
)
registry = Registry()


@registry.activity()
async def read_request_id() -> str:
    return REQUEST_ID.get()


@registry.workflow()
class RequestIdWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await read_request_id.with_options(
            schedule_to_close_timeout=timedelta(seconds=30)
        ).execute()


async def main() -> None:
    domain = os.environ.get("CADENCE_DOMAIN", "default")
    target = os.environ.get("CADENCE_TARGET", "localhost:7833")
    task_list = "context-propagation-example"
    client = Client(
        domain=domain,
        target=target,
        context_propagators=(REQUEST_ID_PROPAGATOR,),
    )

    async with client, Worker(client, task_list, registry):
        token = REQUEST_ID.set("example-request-id")
        try:
            execution = await client.start_workflow(
                "RequestIdWorkflow",
                task_list=task_list,
                execution_start_to_close_timeout=timedelta(minutes=1),
            )
        finally:
            REQUEST_ID.reset(token)

        history = await client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=domain,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )
        result = history.history.events[
            -1
        ].workflow_execution_completed_event_attributes.result.data.decode()
        print(f"Workflow received request context: {result}")


if __name__ == "__main__":
    asyncio.run(main())
