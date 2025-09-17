#!/usr/bin/env python3
"""
Integration tests for WorkflowEngine.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.api.v1.common_pb2 import Payload, WorkflowExecution, WorkflowType
from cadence.api.v1.history_pb2 import History, HistoryEvent, WorkflowExecutionStartedEventAttributes
from cadence._internal.workflow.workflow_engine import WorkflowEngine, DecisionResult
from cadence.workflow import WorkflowInfo
from cadence.client import Client


class TestWorkflowEngineIntegration:
    """Integration tests for WorkflowEngine."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Cadence client."""
        client = Mock(spec=Client)
        client.domain = "test-domain"
        client.data_converter = Mock()
        client.data_converter.from_data = AsyncMock(return_value=["test-input"])
        return client

    @pytest.fixture
    def workflow_info(self):
        """Create workflow info."""
        return WorkflowInfo(
            workflow_type="test_workflow",
            workflow_domain="test-domain",
            workflow_id="test-workflow-id",
            workflow_run_id="test-run-id"
        )

    @pytest.fixture
    def mock_workflow_func(self):
        """Create a mock workflow function."""
        def workflow_func(input_data):
            return f"processed: {input_data}"
        return workflow_func

    @pytest.fixture
    def workflow_engine(self, mock_client, workflow_info, mock_workflow_func):
        """Create a WorkflowEngine instance."""
        return WorkflowEngine(
            info=workflow_info,
            client=mock_client,
            workflow_func=mock_workflow_func
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
    async def test_process_decision_success(self, workflow_engine, mock_client):
        """Test successful decision processing."""
        decision_task = self.create_mock_decision_task()
        
        # Mock the decision manager to return some decisions
        with patch.object(workflow_engine._decision_manager, 'collect_pending_decisions', return_value=[Mock()]):
            # Process the decision
            result = await workflow_engine.process_decision(decision_task)
            
            # Verify the result
            assert isinstance(result, DecisionResult)
            assert len(result.decisions) == 1
            assert result.force_create_new_decision_task is False
            assert result.query_results is None

    @pytest.mark.asyncio
    async def test_process_decision_with_history(self, workflow_engine, mock_client):
        """Test decision processing with history events."""
        decision_task = self.create_mock_decision_task()
        
        # Mock the decision manager
        with patch.object(workflow_engine._decision_manager, 'handle_history_event') as mock_handle:
            with patch.object(workflow_engine._decision_manager, 'collect_pending_decisions', return_value=[]):
                # Process the decision
                await workflow_engine.process_decision(decision_task)
                
                # Verify history events were processed
                mock_handle.assert_called()

    @pytest.mark.asyncio
    async def test_process_decision_workflow_complete(self, workflow_engine, mock_client):
        """Test decision processing when workflow is already complete."""
        # Mark workflow as complete
        workflow_engine._is_workflow_complete = True
        
        decision_task = self.create_mock_decision_task()
        
        with patch.object(workflow_engine._decision_manager, 'collect_pending_decisions', return_value=[]):
            # Process the decision
            result = await workflow_engine.process_decision(decision_task)
            
            # Verify the result
            assert isinstance(result, DecisionResult)
            assert len(result.decisions) == 0

    @pytest.mark.asyncio
    async def test_process_decision_error_handling(self, workflow_engine, mock_client):
        """Test decision processing error handling."""
        decision_task = self.create_mock_decision_task()
        
        # Mock the decision manager to raise an exception
        with patch.object(workflow_engine._decision_manager, 'handle_history_event', side_effect=Exception("Test error")):
            # Process the decision
            result = await workflow_engine.process_decision(decision_task)
            
            # Verify error handling - should return empty decisions
            assert isinstance(result, DecisionResult)
            assert len(result.decisions) == 0

    @pytest.mark.asyncio
    async def test_extract_workflow_input_success(self, workflow_engine, mock_client):
        """Test successful workflow input extraction."""
        decision_task = self.create_mock_decision_task()
        
        # Extract workflow input
        input_data = await workflow_engine._extract_workflow_input(decision_task)
        
        # Verify the input was extracted
        assert input_data == "test-input"
        mock_client.data_converter.from_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_workflow_input_no_history(self, workflow_engine, mock_client):
        """Test workflow input extraction with no history."""
        decision_task = PollForDecisionTaskResponse()
        decision_task.task_token = b"test-task-token"
        # No history set
        
        # Extract workflow input
        input_data = await workflow_engine._extract_workflow_input(decision_task)
        
        # Verify no input was extracted
        assert input_data is None

    @pytest.mark.asyncio
    async def test_extract_workflow_input_no_started_event(self, workflow_engine, mock_client):
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
        input_data = await workflow_engine._extract_workflow_input(decision_task)
        
        # Verify no input was extracted
        assert input_data is None

    @pytest.mark.asyncio
    async def test_extract_workflow_input_deserialization_error(self, workflow_engine, mock_client):
        """Test workflow input extraction with deserialization error."""
        decision_task = self.create_mock_decision_task()
        
        # Mock data converter to raise an exception
        mock_client.data_converter.from_data = AsyncMock(side_effect=Exception("Deserialization error"))
        
        # Extract workflow input
        input_data = await workflow_engine._extract_workflow_input(decision_task)
        
        # Verify no input was extracted due to error
        assert input_data is None

    def test_execute_workflow_function_sync(self, workflow_engine):
        """Test synchronous workflow function execution."""
        input_data = "test-input"
        
        # Execute the workflow function
        result = workflow_engine._execute_workflow_function_sync(workflow_engine._workflow_func, input_data)
        
        # Verify the result
        assert result == "processed: test-input"

    def test_execute_workflow_function_async(self, workflow_engine):
        """Test asynchronous workflow function execution."""
        async def async_workflow_func(input_data):
            return f"async-processed: {input_data}"
        
        input_data = "test-input"
        
        # Execute the async workflow function
        result = workflow_engine._execute_workflow_function_sync(async_workflow_func, input_data)
        
        # Verify the result
        assert result == "async-processed: test-input"

    def test_execute_workflow_function_none(self, workflow_engine):
        """Test workflow function execution with None function."""
        input_data = "test-input"
        
        # Execute with None workflow function - should raise TypeError
        with pytest.raises(TypeError, match="'NoneType' object is not callable"):
            workflow_engine._execute_workflow_function_sync(None, input_data)

    def test_workflow_engine_initialization(self, workflow_engine, workflow_info, mock_client, mock_workflow_func):
        """Test WorkflowEngine initialization."""
        assert workflow_engine._context is not None
        assert workflow_engine._workflow_func == mock_workflow_func
        assert workflow_engine._decision_manager is not None
        assert workflow_engine._is_workflow_complete is False

    @pytest.mark.asyncio
    async def test_workflow_engine_without_workflow_func(self, mock_client, workflow_info):
        """Test WorkflowEngine without workflow function."""
        engine = WorkflowEngine(
            info=workflow_info,
            client=mock_client,
            workflow_func=None
        )
        
        decision_task = self.create_mock_decision_task()
        
        with patch.object(engine._decision_manager, 'collect_pending_decisions', return_value=[]):
            # Process the decision
            result = await engine.process_decision(decision_task)
            
            # Verify the result
            assert isinstance(result, DecisionResult)
            assert len(result.decisions) == 0

    @pytest.mark.asyncio
    async def test_workflow_engine_workflow_completion(self, workflow_engine, mock_client):
        """Test workflow completion detection."""
        decision_task = self.create_mock_decision_task()
        
        # Mock workflow function to return a result (indicating completion)
        def completing_workflow_func(input_data):
            return "workflow-completed"
        
        workflow_engine._workflow_func = completing_workflow_func
        
        with patch.object(workflow_engine._decision_manager, 'collect_pending_decisions', return_value=[]):
            # Process the decision
            await workflow_engine.process_decision(decision_task)
            
            # Verify workflow is marked as complete
            assert workflow_engine._is_workflow_complete is True

    def test_close_event_loop(self, workflow_engine):
        """Test event loop closing."""
        # This should not raise an exception
        workflow_engine._close_event_loop()

    @pytest.mark.asyncio
    async def test_process_decision_with_query_results(self, workflow_engine, mock_client):
        """Test decision processing with query results."""
        decision_task = self.create_mock_decision_task()
        
        # Mock the decision manager to return decisions with query results
        mock_decisions = [Mock()]
        
        with patch.object(workflow_engine._decision_manager, 'collect_pending_decisions', return_value=mock_decisions):
            # Process the decision
            result = await workflow_engine.process_decision(decision_task)
            
            # Verify the result
            assert isinstance(result, DecisionResult)
            assert len(result.decisions) == 1
            assert result.force_create_new_decision_task is False
            assert result.query_results is None  # Not set in this test
