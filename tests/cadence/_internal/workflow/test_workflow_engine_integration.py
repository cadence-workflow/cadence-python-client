#!/usr/bin/env python3
"""
Integration tests for WorkflowEngine.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.api.v1.common_pb2 import Payload, WorkflowExecution, WorkflowType
from cadence.api.v1.history_pb2 import (
    History,
    HistoryEvent,
    WorkflowExecutionStartedEventAttributes,
)
from cadence._internal.workflow.workflow_engine import WorkflowEngine, DecisionResult
from cadence import workflow
from cadence.workflow import WorkflowInfo, WorkflowDefinition, WorkflowDefinitionOptions
from cadence.client import Client


class TestWorkflowEngineIntegration:
    """Integration tests for WorkflowEngine."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Cadence client."""
        client = Mock(spec=Client)
        client.domain = "test-domain"
        client.data_converter = Mock()
        client.data_converter.from_data = Mock(return_value=["test-input"])
        return client

    @pytest.fixture
    def workflow_info(self, mock_client, decision_task):
        """Create workflow info."""
        return WorkflowInfo(
            workflow_type="test_workflow",
            workflow_domain="test-domain",
            workflow_id="test-workflow-id",
            workflow_run_id="test-run-id",
            workflow_task_list="test-task-list",
            workflow_events=decision_task.history.events,
            data_converter=mock_client.data_converter,
        )

    @pytest.fixture
    def decision_task(self):
        return self.create_mock_decision_task()

    @pytest.fixture
    def mock_workflow_definition(self):
        """Create a mock workflow definition."""

        class TestWorkflow:
            @workflow.run
            async def weird_name(self, input_data):
                return f"processed: {input_data}"

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        return WorkflowDefinition.wrap(TestWorkflow, workflow_opts)

    @pytest.fixture
    def workflow_engine(self, workflow_info, mock_workflow_definition):
        """Create a WorkflowEngine instance."""
        return WorkflowEngine(
            info=workflow_info,
            workflow_definition=mock_workflow_definition,
        )

    def create_mock_decision_task(
        self,
        workflow_id="test-workflow",
        run_id="test-run",
        workflow_type="test_workflow",
    ):
        """Create a mock decision task with history."""
        # Create workflow execution
        workflow_execution = WorkflowExecution()
        workflow_execution.workflow_id = workflow_id
        workflow_execution.run_id = run_id

        # Create workflow type
        workflow_type_obj = WorkflowType()
        workflow_type_obj.name = workflow_type

        # Create workflow execution started event
        started_event = WorkflowExecutionStartedEventAttributes()
        input_payload = Payload(data=b'"test-input"')
        started_event.input.CopyFrom(input_payload)

        history_event = HistoryEvent()
        history_event.workflow_execution_started_event_attributes.CopyFrom(
            started_event
        )

        # Create history
        history = History()
        history.events.append(history_event)

        # Create decision task
        decision_task = PollForDecisionTaskResponse()
        decision_task.task_token = b"test-task-token"
        decision_task.workflow_execution.CopyFrom(workflow_execution)
        decision_task.workflow_type.CopyFrom(workflow_type_obj)
        decision_task.history.CopyFrom(history)

        return decision_task

    def test_process_decision_success(self, workflow_engine, decision_task):
        """Test successful decision processing."""

        # Mock the decision manager to return some decisions
        with patch.object(
            workflow_engine._decision_manager,
            "collect_pending_decisions",
            return_value=[Mock()],
        ):
            # Process the decision
            result = workflow_engine.process_decision(decision_task)

            # Verify the result
            assert isinstance(result, DecisionResult)
            assert len(result.decisions) == 1

    def test_process_decision_error_handling(
        self, workflow_engine, mock_client, decision_task
    ):
        """Test decision processing error handling."""

        # Mock the decision manager to raise an exception
        with patch.object(
            workflow_engine._decision_manager,
            "handle_history_event",
            side_effect=Exception("Test error"),
        ):
            # Process the decision
            result = workflow_engine.process_decision(decision_task)

            # Verify error handling - should return empty decisions
            assert isinstance(result, DecisionResult)
            assert len(result.decisions) == 0

    @pytest.mark.asyncio
    async def test_extract_workflow_input_success(
        self, workflow_engine: "WorkflowEngine", mock_client, decision_task
    ):
        """Test successful workflow input extraction."""

        # Extract workflow input
        input_data = workflow_engine._extract_workflow_input(decision_task)

        # Verify the input was extracted
        assert input_data == "test-input"
        mock_client.data_converter.from_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_workflow_input_no_history(
        self, workflow_engine, mock_client
    ):
        """Test workflow input extraction with no history."""
        decision_task = PollForDecisionTaskResponse()
        decision_task.task_token = b"test-task-token"
        # No history set

        # Extract workflow input
        input_data = workflow_engine._extract_workflow_input(decision_task)

        # Verify no input was extracted
        assert input_data is None

    @pytest.mark.asyncio
    async def test_extract_workflow_input_no_started_event(
        self, workflow_engine, mock_client
    ):
        """Test workflow input extraction with no WorkflowExecutionStarted event."""
        # Create a decision task with no started event
        decision_task = PollForDecisionTaskResponse()
        decision_task.task_token = b"test-task-token"

        # Create workflow execution
        workflow_execution = WorkflowExecution()
        workflow_execution.workflow_id = "test-workflow"
        workflow_execution.run_id = "test-run"
        decision_task.workflow_execution.CopyFrom(workflow_execution)

        # Create workflow type
        workflow_type_obj = WorkflowType()
        workflow_type_obj.name = "test_workflow"
        decision_task.workflow_type.CopyFrom(workflow_type_obj)

        # Create history with no events
        history = History()
        decision_task.history.CopyFrom(history)

        # Extract workflow input
        input_data = workflow_engine._extract_workflow_input(decision_task)

        # Verify no input was extracted
        assert input_data is None

    @pytest.mark.asyncio
    async def test_extract_workflow_input_deserialization_error(
        self, workflow_engine, mock_client, decision_task
    ):
        """Test workflow input extraction with deserialization error."""

        # Mock data converter to raise an exception
        mock_client.data_converter.from_data = AsyncMock(
            side_effect=Exception("Deserialization error")
        )

        # Extract workflow input
        input_data = workflow_engine._extract_workflow_input(decision_task)

        # Verify no input was extracted due to error
        assert input_data is None

    def test_process_decision_with_query_results(
        self, workflow_engine, mock_client, decision_task
    ):
        """Test decision processing with query results."""

        # Mock the decision manager to return decisions with query results
        mock_decisions = [Mock()]

        with patch.object(
            workflow_engine._decision_manager,
            "collect_pending_decisions",
            return_value=mock_decisions,
        ):
            # Process the decision
            result = workflow_engine.process_decision(decision_task)

            # Verify the result
            assert isinstance(result, DecisionResult)
            assert len(result.decisions) == 1
