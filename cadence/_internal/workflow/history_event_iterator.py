
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.api.v1.service_workflow_pb2 import GetWorkflowExecutionHistoryRequest, GetWorkflowExecutionHistoryResponse
from cadence.client import Client

async def iterate_history_events(decision_task: PollForDecisionTaskResponse, client: Client):
    PAGE_SIZE = 1000

    current_page = decision_task.history.events
    next_page_token = decision_task.next_page_token
    workflow_execution = decision_task.workflow_execution

    while True:
        for event in current_page:
            yield event
        if not next_page_token:
            break
        response: GetWorkflowExecutionHistoryResponse = await client.workflow_stub.GetWorkflowExecutionHistory(GetWorkflowExecutionHistoryRequest(
            domain=client.domain,
            workflow_execution=workflow_execution,
            next_page_token=next_page_token,
            page_size=PAGE_SIZE,
        ))
        current_page = response.history.events
        next_page_token = response.next_page_token
