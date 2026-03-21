#!/usr/bin/env python3
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from agents import Agent, RunConfig, Runner, function_tool
from agents.run import set_default_agent_runner
import cadence

from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import GetWorkflowExecutionHistoryRequest, GetWorkflowExecutionHistoryResponse
import cadence.worker
from contrib.openai.agent_runner import CadenceAgentRunner
from contrib.openai.openai_activities import OpenAIActivities
from contrib.openai.pydantic_data_converter import PydanticDataConverter

CADENCE_DOMAIN_NAME = "default"
CADENCE_FRONTEND_TARGET = "localhost:7833"
cadence_registry = cadence.Registry()
cadence_registry.register_activities(OpenAIActivities())

@dataclass
class Flight:
    from_city: str
    to_city: str
    departure_date: datetime
    return_date: datetime
    price: float
    airline: str
    flight_number: str
    seat_number: str

@cadence_registry.activity(name="book_flight")
async def book_flight(from_city: str, to_city: str, departure_date: datetime, return_date: datetime) -> Flight:
    """
    Book a flight tool
    """
    return Flight(from_city=from_city, to_city=to_city, departure_date=departure_date, return_date=return_date, price=100, airline="United", flight_number="123456", seat_number="12A")

@cadence_registry.workflow(name="BookFlightAgentWorkflow")
class BookFlightAgentWorkflow:

    @cadence.workflow.run
    async def run(self, input: str) -> str:

        agent =Agent(
            name = "Book Flight Agent",
            model = "gpt-4o-mini",
            tools = [
                function_tool(book_flight),
            ],
        )
        result = await Runner.run(agent, input, run_config=RunConfig(
                tracing_disabled=True,
            ))
        return result.final_output

async def main():
    set_default_agent_runner(CadenceAgentRunner())
    worker = cadence.worker.Worker(
        cadence.Client(
            domain=CADENCE_DOMAIN_NAME,
            target=CADENCE_FRONTEND_TARGET,
            data_converter=PydanticDataConverter(),
        ),
        "agent-task-list",
        cadence_registry,
    )

    async with worker.run() as worker:
        execution = await worker.client.start_workflow(
            "BookFlightAgentWorkflow",
            "Book a flight from New York to London on March 20th 2026 at 10:00 AM and return on March 25th, 2026 at 10:00 AM",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(minutes=10),
        )

        print(f"cadence workflow started: http://localhost:8088/domains/default/cluster0/workflows/{execution.workflow_id}/{execution.run_id}/summary")

        # get workflow result
        response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=worker.client.domain,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        return response.history.events[-1].workflow_execution_completed_event_attributes.result.data.decode()


if __name__ == "__main__":
    asyncio.run(main())
