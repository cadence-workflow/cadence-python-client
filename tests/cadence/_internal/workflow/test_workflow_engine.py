#!/usr/bin/env python3
from typing import List
import pytest
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.history_pb2 import (
    DecisionTaskCompletedEventAttributes,
    DecisionTaskScheduledEventAttributes,
    DecisionTaskStartedEventAttributes,
    HistoryEvent,
    WorkflowExecutionCompletedEventAttributes,
    WorkflowExecutionStartedEventAttributes,
)
from cadence._internal.workflow.workflow_engine import WorkflowEngine
from cadence import workflow
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo, WorkflowDefinition, WorkflowDefinitionOptions


class TestWorkflow:
    @workflow.run
    async def echo(self, input_data):
        return f"echo: {input_data}"


class TestWorkflowEngine:
    """Unit tests for WorkflowEngine."""

    @pytest.fixture
    def echo_workflow_definition(self) -> WorkflowDefinition:
        """Create a mock workflow definition."""
        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        return WorkflowDefinition.wrap(TestWorkflow, workflow_opts)

    @pytest.fixture
    def simple_workflow_events(self) -> List[HistoryEvent]:
        return [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b'"test-input"')
                ),
            ),
            HistoryEvent(
                event_id=2,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=3,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=2
                ),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_completed_event_attributes=DecisionTaskCompletedEventAttributes(
                    scheduled_event_id=2,
                ),
            ),
            HistoryEvent(
                event_id=5,
                workflow_execution_completed_event_attributes=WorkflowExecutionCompletedEventAttributes(
                    result=Payload(data=b'"echo: test-input"')
                ),
            ),
        ]

    def test_process_simple_workflow(
        self,
        echo_workflow_definition: WorkflowDefinition,
        simple_workflow_events: List[HistoryEvent],
    ):
        workflow_engine = create_workflow_engine(echo_workflow_definition)
        decision_result = workflow_engine.process_decision(simple_workflow_events[:3])
        assert len(decision_result.decisions) == 1
        assert decision_result.decisions[
            0
        ].complete_workflow_execution_decision_attributes.result == Payload(
            data=b'"echo: test-input"'
        )


def create_workflow_engine(workflow_definition: WorkflowDefinition) -> WorkflowEngine:
    """Create workflow engine."""
    return WorkflowEngine(
        info=WorkflowInfo(
            workflow_type="test_workflow",
            workflow_domain="test-domain",
            workflow_id="test-workflow-id",
            workflow_run_id="test-run-id",
            workflow_task_list="test-task-list",
            data_converter=DefaultDataConverter(),
        ),
        workflow_definition=workflow_definition,
    )
