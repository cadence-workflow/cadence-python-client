#!/usr/bin/env python3
"""
Integration tests for DecisionWorker with DecisionTaskHandler.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.api.v1.common_pb2 import Payload, WorkflowExecution, WorkflowType
from cadence.api.v1.history_pb2 import History, HistoryEvent, WorkflowExecutionStartedEventAttributes
from cadence.worker._decision_worker import DecisionWorker
from cadence.worker._registry import Registry
from cadence.client import Client


class TestDecisionWorkerIntegration:
    """Integration tests for DecisionWorker with DecisionTaskHandler."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Cadence client."""
        client = Mock(spec=Client)
        client.domain = "test-domain"
        client.data_converter = Mock()
        client.data_converter.from_data = AsyncMock(return_value=["test-input"])
        client.worker_stub = Mock()
        client.worker_stub.PollForDecisionTask = AsyncMock()
        client.worker_stub.RespondDecisionTaskCompleted = AsyncMock()
        client.worker_stub.RespondDecisionTaskFailed = AsyncMock()
        return client

    @pytest.fixture
    def registry(self):
        """Create a registry with a test workflow."""
        reg = Registry()
        
        @reg.workflow
        def test_workflow(input_data):
            """Simple test workflow that returns the input."""
            return f"processed: {input_data}"
        
        return reg

    @pytest.fixture
    def decision_worker(self, mock_client, registry):
        """Create a DecisionWorker instance."""
        options = {
            "identity": "test-worker",
            "max_concurrent_decision_task_execution_size": 1,
            "decision_task_pollers": 1
        }
        return DecisionWorker(
            client=mock_client,
            task_list="test-task-list",
            registry=registry,
            options=options
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
    async def test_decision_worker_poll_and_execute(self, decision_worker, mock_client):
        """Test decision worker polling and executing tasks."""
        # Create a mock decision task
        decision_task = self.create_mock_decision_task()
        
        # Mock the poll to return the decision task
        mock_client.worker_stub.PollForDecisionTask.return_value = decision_task
        
        # Mock the decision handler
        with patch.object(decision_worker, '_decision_handler') as mock_handler:
            mock_handler.handle_task = AsyncMock()
            
            # Run the poll and execute
            await decision_worker._poll()
            await decision_worker._execute(decision_task)
            
            # Verify the poll was called
            mock_client.worker_stub.PollForDecisionTask.assert_called_once()
            
            # Verify the handler was called
            mock_handler.handle_task.assert_called_once_with(decision_task)

    @pytest.mark.asyncio
    async def test_decision_worker_poll_no_task(self, decision_worker, mock_client):
        """Test decision worker polling when no task is available."""
        # Mock the poll to return None (no task)
        mock_client.worker_stub.PollForDecisionTask.return_value = None
        
        # Run the poll
        result = await decision_worker._poll()
        
        # Verify no task was returned
        assert result is None

    @pytest.mark.asyncio
    async def test_decision_worker_poll_with_task_token(self, decision_worker, mock_client):
        """Test decision worker polling when task has token."""
        # Create a decision task with token
        decision_task = self.create_mock_decision_task()
        decision_task.task_token = b"valid-token"
        
        # Mock the poll to return the decision task
        mock_client.worker_stub.PollForDecisionTask.return_value = decision_task
        
        # Run the poll
        result = await decision_worker._poll()
        
        # Verify the task was returned
        assert result == decision_task

    @pytest.mark.asyncio
    async def test_decision_worker_poll_without_task_token(self, decision_worker, mock_client):
        """Test decision worker polling when task has no token."""
        # Create a decision task without token
        decision_task = self.create_mock_decision_task()
        decision_task.task_token = b""  # Empty token
        
        # Mock the poll to return the decision task
        mock_client.worker_stub.PollForDecisionTask.return_value = decision_task
        
        # Run the poll
        result = await decision_worker._poll()
        
        # Verify no task was returned
        assert result is None

    @pytest.mark.asyncio
    async def test_decision_worker_execute_success(self, decision_worker, mock_client):
        """Test successful decision task execution."""
        decision_task = self.create_mock_decision_task()
        
        # Mock the decision handler
        with patch.object(decision_worker, '_decision_handler') as mock_handler:
            mock_handler.handle_task = AsyncMock()
            
            # Execute the task
            await decision_worker._execute(decision_task)
            
            # Verify the handler was called
            mock_handler.handle_task.assert_called_once_with(decision_task)

    @pytest.mark.asyncio
    async def test_decision_worker_execute_handler_error(self, decision_worker, mock_client):
        """Test decision task execution when handler raises an error."""
        decision_task = self.create_mock_decision_task()
        
        # Mock the decision handler to raise an error
        with patch.object(decision_worker, '_decision_handler') as mock_handler:
            mock_handler.handle_task = AsyncMock(side_effect=Exception("Handler error"))
            
            # Execute the task - should raise the exception
            with pytest.raises(Exception, match="Handler error"):
                await decision_worker._execute(decision_task)
            
            # Verify the handler was called
            mock_handler.handle_task.assert_called_once_with(decision_task)

    def test_decision_worker_initialization(self, decision_worker, mock_client, registry):
        """Test DecisionWorker initialization."""
        assert decision_worker._client == mock_client
        assert decision_worker._task_list == "test-task-list"
        assert decision_worker._identity == "test-worker"
        assert decision_worker._registry == registry
        assert decision_worker._decision_handler is not None
        assert decision_worker._poller is not None

    @pytest.mark.asyncio
    async def test_decision_worker_run(self, decision_worker, mock_client):
        """Test DecisionWorker run method."""
        # Mock the poller to complete immediately
        with patch.object(decision_worker._poller, 'run', new_callable=AsyncMock) as mock_poller_run:
            # Run the worker
            await decision_worker.run()
            
            # Verify the poller was run
            mock_poller_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_decision_worker_integration_flow(self, decision_worker, mock_client):
        """Test the complete integration flow from poll to execute."""
        # Create a mock decision task
        decision_task = self.create_mock_decision_task()
        
        # Mock the poll to return the decision task
        mock_client.worker_stub.PollForDecisionTask.return_value = decision_task
        
        # Mock the decision handler
        with patch.object(decision_worker, '_decision_handler') as mock_handler:
            mock_handler.handle_task = AsyncMock()
            
            # Test the complete flow
            # 1. Poll for task
            polled_task = await decision_worker._poll()
            assert polled_task == decision_task
            
            # 2. Execute the task
            await decision_worker._execute(polled_task)
            
            # 3. Verify the handler was called
            mock_handler.handle_task.assert_called_once_with(decision_task)

    @pytest.mark.asyncio
    async def test_decision_worker_with_different_workflow_types(self, decision_worker, mock_client, registry):
        """Test decision worker with different workflow types."""
        # Add another workflow to the registry
        @registry.workflow
        def another_workflow(input_data):
            return f"another-processed: {input_data}"
        
        # Create decision tasks for different workflow types
        task1 = self.create_mock_decision_task(workflow_type="test_workflow")
        task2 = self.create_mock_decision_task(workflow_type="another_workflow")
        
        # Mock the decision handler
        with patch.object(decision_worker, '_decision_handler') as mock_handler:
            mock_handler.handle_task = AsyncMock()
            
            # Execute both tasks
            await decision_worker._execute(task1)
            await decision_worker._execute(task2)
            
            # Verify both tasks were handled
            assert mock_handler.handle_task.call_count == 2

    @pytest.mark.asyncio
    async def test_decision_worker_poll_timeout(self, decision_worker, mock_client):
        """Test decision worker polling with timeout."""
        # Mock the poll to raise a timeout exception
        mock_client.worker_stub.PollForDecisionTask.side_effect = asyncio.TimeoutError("Poll timeout")
        
        # Run the poll - should handle timeout gracefully
        with pytest.raises(asyncio.TimeoutError):
            await decision_worker._poll()

    def test_decision_worker_options_handling(self, mock_client, registry):
        """Test DecisionWorker with various options."""
        options = {
            "identity": "custom-worker",
            "max_concurrent_decision_task_execution_size": 5,
            "decision_task_pollers": 3
        }
        
        worker = DecisionWorker(
            client=mock_client,
            task_list="custom-task-list",
            registry=registry,
            options=options
        )
        
        # Verify options were applied
        assert worker._identity == "custom-worker"
        assert worker._task_list == "custom-task-list"
        assert worker._registry == registry
