#!/usr/bin/env python3
"""
Integration tests for DecisionTaskHandler and WorkflowEngine.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from cadence.api.v1.service_worker_pb2 import (
    PollForDecisionTaskResponse
)
from cadence.api.v1.common_pb2 import Payload, WorkflowExecution, WorkflowType
from cadence.api.v1.history_pb2 import History, HistoryEvent, WorkflowExecutionStartedEventAttributes
from cadence.api.v1.decision_pb2 import Decision
from cadence.worker._decision_task_handler import DecisionTaskHandler
from cadence.worker._registry import Registry
from cadence import workflow
from cadence.client import Client


class TestDecisionTaskHandlerIntegration:
    """Integration tests for DecisionTaskHandler."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Cadence client."""
        client = Mock(spec=Client)
        client.domain = "test-domain"
        client.data_converter = Mock()
        client.data_converter.from_data = AsyncMock(return_value=["test-input"])
        client.worker_stub = Mock()
        client.worker_stub.RespondDecisionTaskCompleted = AsyncMock()
        client.worker_stub.RespondDecisionTaskFailed = AsyncMock()
        return client

    @pytest.fixture
    def registry(self):
        """Create a registry with a test workflow."""
        reg = Registry()

        @reg.workflow(name="test_workflow")
        class TestWorkflow:
            @workflow.run
            async def run(self, input_data):
                """Simple test workflow that returns the input."""
                return f"processed: {input_data}"

        return reg

    @pytest.fixture
    def decision_task_handler(self, mock_client, registry):
        """Create a DecisionTaskHandler instance."""
        return DecisionTaskHandler(
            client=mock_client,
            task_list="test-task-list",
            registry=registry,
            identity="test-worker"
        )

    def create_mock_decision_task(self, workflow_id="test-workflow", run_id="test-run", workflow_type="test_workflow"):
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
        history_event.workflow_execution_started_event_attributes.CopyFrom(started_event)
        
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

    @pytest.mark.asyncio
    async def test_handle_decision_task_success(self, decision_task_handler, mock_client):
        """Test successful decision task handling."""
        # Create a mock decision task
        decision_task = self.create_mock_decision_task()
        
        # Mock the workflow engine to return some decisions
        # Mock the workflow engine creation and execution
        mock_engine = Mock()
        # Create a proper Decision object
        decision = Decision()
        mock_engine.process_decision = AsyncMock(return_value=Mock(
            decisions=[decision],  # Proper Decision object
        ))
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine):
            # Handle the decision task
            await decision_task_handler._handle_task_implementation(decision_task)
            
            # Verify the workflow engine was called
            mock_engine.process_decision.assert_called_once_with(decision_task)
            
            # Verify the response was sent
            mock_client.worker_stub.RespondDecisionTaskCompleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_decision_task_workflow_not_found(self, decision_task_handler, mock_client):
        """Test decision task handling when workflow is not found in registry."""
        # Create a decision task with unknown workflow type
        decision_task = self.create_mock_decision_task(workflow_type="unknown_workflow")
        
        # Handle the decision task
        await decision_task_handler.handle_task(decision_task)
        
        # Verify failure response was sent
        mock_client.worker_stub.RespondDecisionTaskFailed.assert_called_once()
        
        # Verify the failure request has the correct cause
        call_args = mock_client.worker_stub.RespondDecisionTaskFailed.call_args[0][0]
        assert call_args.cause == 14  # DECISION_TASK_FAILED_CAUSE_WORKFLOW_WORKER_UNHANDLED_FAILURE

    @pytest.mark.asyncio
    async def test_handle_decision_task_missing_workflow_execution(self, decision_task_handler, mock_client):
        """Test decision task handling when workflow execution is missing."""
        # Create a decision task without workflow execution
        decision_task = PollForDecisionTaskResponse()
        decision_task.task_token = b"test-task-token"
        # No workflow_execution set
        
        # Handle the decision task
        await decision_task_handler.handle_task(decision_task)
        
        # Verify failure response was sent
        mock_client.worker_stub.RespondDecisionTaskFailed.assert_called_once()
        
        # Verify the failure request has the correct cause
        call_args = mock_client.worker_stub.RespondDecisionTaskFailed.call_args[0][0]
        assert call_args.cause == 14  # DECISION_TASK_FAILED_CAUSE_WORKFLOW_WORKER_UNHANDLED_FAILURE

    @pytest.mark.asyncio
    async def test_workflow_engine_creation_each_task(self, decision_task_handler, mock_client):
        """Test that workflow engines are created for each task."""
        decision_task = self.create_mock_decision_task()
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine') as mock_engine_class:
            mock_engine = Mock()
            mock_engine.process_decision = AsyncMock(return_value=Mock(
                decisions=[],
            ))
            mock_engine_class.return_value = mock_engine
            
            # Handle the same decision task twice
            await decision_task_handler._handle_task_implementation(decision_task)
            await decision_task_handler._handle_task_implementation(decision_task)
            
            # Verify engine was created twice (once for each task)
            assert mock_engine_class.call_count == 2
            
            # Verify engine was called twice
            assert mock_engine.process_decision.call_count == 2


    @pytest.mark.asyncio
    async def test_decision_task_failure_handling(self, decision_task_handler, mock_client):
        """Test decision task failure handling."""
        decision_task = self.create_mock_decision_task()
        
        # Mock the workflow engine to raise an exception
        with patch('cadence.worker._decision_task_handler.WorkflowEngine') as mock_engine_class:
            mock_engine = Mock()
            mock_engine.process_decision = AsyncMock(side_effect=Exception("Test error"))
            mock_engine_class.return_value = mock_engine
            
            # Handle the decision task - this should catch the exception
            await decision_task_handler.handle_task(decision_task)
            
            # Verify failure response was sent
            mock_client.worker_stub.RespondDecisionTaskFailed.assert_called_once()

    def test_decision_task_handler_initialization(self, decision_task_handler):
        """Test DecisionTaskHandler initialization."""
        assert decision_task_handler._registry is not None
        assert decision_task_handler._identity == "test-worker"

    @pytest.mark.asyncio
    async def test_respond_decision_task_completed(self, decision_task_handler, mock_client):
        """Test decision task completion response."""
        decision_task = self.create_mock_decision_task()
        
        # Create mock decision result
        decision_result = Mock()
        decision_result.decisions = [Decision()]  # Proper Decision object
        
        # Call the response method
        await decision_task_handler._respond_decision_task_completed(decision_task, decision_result)
        
        # Verify the response was sent
        mock_client.worker_stub.RespondDecisionTaskCompleted.assert_called_once()
        
        # Verify the request parameters
        call_args = mock_client.worker_stub.RespondDecisionTaskCompleted.call_args[0][0]
        assert call_args.task_token == b"test-task-token"
        assert call_args.identity == "test-worker"
        assert len(call_args.decisions) == 1

    @pytest.mark.asyncio
    async def test_respond_decision_task_failed(self, decision_task_handler, mock_client):
        """Test decision task failure response."""
        decision_task = self.create_mock_decision_task()
        error = ValueError("Test error")
        
        # Call the failure method
        await decision_task_handler.handle_task_failure(decision_task, error)
        
        # Verify the failure response was sent
        mock_client.worker_stub.RespondDecisionTaskFailed.assert_called_once()
        
        # Verify the request parameters
        call_args = mock_client.worker_stub.RespondDecisionTaskFailed.call_args[0][0]
        assert call_args.task_token == b"test-task-token"
        assert call_args.identity == "test-worker"
        assert call_args.cause == 2  # BAD_SCHEDULE_ACTIVITY_ATTRIBUTES for ValueError
        assert b"Test error" in call_args.details.data
