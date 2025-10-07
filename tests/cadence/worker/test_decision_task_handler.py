#!/usr/bin/env python3
"""
Unit tests for DecisionTaskHandler class.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, PropertyMock

from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.service_worker_pb2 import (
    PollForDecisionTaskResponse,
    RespondDecisionTaskCompletedRequest
)
from cadence.api.v1.workflow_pb2 import DecisionTaskFailedCause
from cadence.api.v1.decision_pb2 import Decision
from cadence.client import Client
from cadence.worker._decision_task_handler import DecisionTaskHandler
from cadence.worker._registry import Registry
from cadence._internal.workflow.workflow_engine import WorkflowEngine, DecisionResult


class TestDecisionTaskHandler:
    """Test cases for DecisionTaskHandler."""
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock client."""
        client = Mock(spec=Client)
        client.worker_stub = Mock()
        client.worker_stub.RespondDecisionTaskCompleted = AsyncMock()
        client.worker_stub.RespondDecisionTaskFailed = AsyncMock()
        type(client).domain = PropertyMock(return_value="test_domain")
        return client
    
    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry."""
        registry = Mock(spec=Registry)
        return registry
    
    @pytest.fixture
    def handler(self, mock_client, mock_registry):
        """Create a DecisionTaskHandler instance."""
        return DecisionTaskHandler(
            client=mock_client,
            task_list="test_task_list",
            registry=mock_registry,
            identity="test_identity"
        )
    
    @pytest.fixture
    def sample_decision_task(self):
        """Create a sample decision task."""
        task = Mock(spec=PollForDecisionTaskResponse)
        task.task_token = b"test_task_token"
        task.workflow_execution = Mock()
        task.workflow_execution.workflow_id = "test_workflow_id"
        task.workflow_execution.run_id = "test_run_id"
        task.workflow_type = Mock()
        task.workflow_type.name = "TestWorkflow"
        # Add the missing attributes that are now accessed directly
        task.started_event_id = 1
        task.attempt = 1
        return task
    
    def test_initialization(self, mock_client, mock_registry):
        """Test DecisionTaskHandler initialization."""
        handler = DecisionTaskHandler(
            client=mock_client,
            task_list="test_task_list",
            registry=mock_registry,
            identity="test_identity",
            option1="value1"
        )
        
        assert handler._client == mock_client
        assert handler._task_list == "test_task_list"
        assert handler._identity == "test_identity"
        assert handler._registry == mock_registry
        assert handler._options == {"option1": "value1"}
    
    @pytest.mark.asyncio
    async def test_handle_task_implementation_success(self, handler, sample_decision_task, mock_registry):
        """Test successful decision task handling."""
        # Create actual workflow definition
        def mock_workflow_func():
            return "test_result"

        from cadence.workflow import WorkflowDefinition, WorkflowDefinitionOptions
        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(mock_workflow_func, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition
        
        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = [Decision()]
        mock_engine.process_decision = AsyncMock(return_value=mock_decision_result)
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine):
            await handler._handle_task_implementation(sample_decision_task)
        
        # Verify registry was called
        mock_registry.get_workflow.assert_called_once_with("TestWorkflow")
        
        # Verify workflow engine was created and used
        mock_engine.process_decision.assert_called_once_with(sample_decision_task)
        
        # Verify response was sent
        handler._client.worker_stub.RespondDecisionTaskCompleted.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_task_implementation_missing_workflow_execution(self, handler):
        """Test decision task handling with missing workflow execution."""
        task = Mock(spec=PollForDecisionTaskResponse)
        task.task_token = b"test_task_token"
        task.workflow_execution = None
        task.workflow_type = Mock()
        task.workflow_type.name = "TestWorkflow"
        
        with pytest.raises(ValueError, match="Missing workflow execution or type"):
            await handler._handle_task_implementation(task)
    
    @pytest.mark.asyncio
    async def test_handle_task_implementation_missing_workflow_type(self, handler):
        """Test decision task handling with missing workflow type."""
        task = Mock(spec=PollForDecisionTaskResponse)
        task.task_token = b"test_task_token"
        task.workflow_execution = Mock()
        task.workflow_execution.workflow_id = "test_workflow_id"
        task.workflow_execution.run_id = "test_run_id"
        task.workflow_type = None
        
        with pytest.raises(ValueError, match="Missing workflow execution or type"):
            await handler._handle_task_implementation(task)
    
    @pytest.mark.asyncio
    async def test_handle_task_implementation_workflow_not_found(self, handler, sample_decision_task, mock_registry):
        """Test decision task handling when workflow is not found in registry."""
        mock_registry.get_workflow.side_effect = KeyError("Workflow not found")
        
        with pytest.raises(KeyError, match="Workflow type 'TestWorkflow' not found"):
            await handler._handle_task_implementation(sample_decision_task)
    
    @pytest.mark.asyncio
    async def test_handle_task_implementation_caches_engines(self, handler, sample_decision_task, mock_registry):
        """Test that decision task handler caches workflow engines for same workflow execution."""
        # Create actual workflow definition
        def mock_workflow_func():
            return "test_result"

        from cadence.workflow import WorkflowDefinition, WorkflowDefinitionOptions
        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(mock_workflow_func, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition
        
        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_engine.process_decision = AsyncMock(return_value=mock_decision_result)
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine) as mock_engine_class:
            # First call - should create new engine
            await handler._handle_task_implementation(sample_decision_task)
            
            # Second call with same workflow_id and run_id - should reuse cached engine
            await handler._handle_task_implementation(sample_decision_task)
        
        # Registry should be called for each task (to get workflow function)
        assert mock_registry.get_workflow.call_count == 2
        
        # Engine should be created only once (cached for second call)
        assert mock_engine_class.call_count == 1
        
        # But process_decision should be called twice
        assert mock_engine.process_decision.call_count == 2
    
    @pytest.mark.asyncio
    async def test_handle_task_implementation_different_executions_get_separate_engines(self, handler, mock_registry):
        """Test that different workflow executions get separate engines."""
        # Mock workflow function
        mock_workflow_func = Mock()
        mock_registry.get_workflow.return_value = mock_workflow_func
        
        # Create two different decision tasks
        task1 = Mock(spec=PollForDecisionTaskResponse)
        task1.task_token = b"test_task_token_1"
        task1.workflow_execution = Mock()
        task1.workflow_execution.workflow_id = "workflow_1"
        task1.workflow_execution.run_id = "run_1"
        task1.workflow_type = Mock()
        task1.workflow_type.name = "TestWorkflow"
        task1.started_event_id = 1
        task1.attempt = 1
        
        task2 = Mock(spec=PollForDecisionTaskResponse)
        task2.task_token = b"test_task_token_2"
        task2.workflow_execution = Mock()
        task2.workflow_execution.workflow_id = "workflow_2"  # Different workflow
        task2.workflow_execution.run_id = "run_2"          # Different run
        task2.workflow_type = Mock()
        task2.workflow_type.name = "TestWorkflow"
        task2.started_event_id = 2
        task2.attempt = 1
        
        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_engine.process_decision = AsyncMock(return_value=mock_decision_result)
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine) as mock_engine_class:
            # Process different workflow executions
            await handler._handle_task_implementation(task1)
            await handler._handle_task_implementation(task2)
        
        # Registry should be called for each task
        assert mock_registry.get_workflow.call_count == 2
        
        # Engine should be created twice (different executions)
        assert mock_engine_class.call_count == 2
        
        # Process_decision should be called twice
        assert mock_engine.process_decision.call_count == 2
    
    @pytest.mark.asyncio
    async def test_handle_task_failure_keyerror(self, handler, sample_decision_task):
        """Test task failure handling for KeyError."""
        error = KeyError("Workflow not found")
        
        await handler.handle_task_failure(sample_decision_task, error)
        
        # Verify the correct failure cause was used
        call_args = handler._client.worker_stub.RespondDecisionTaskFailed.call_args[0][0]
        assert call_args.cause == DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_WORKFLOW_WORKER_UNHANDLED_FAILURE
        assert call_args.task_token == sample_decision_task.task_token
        assert call_args.identity == handler._identity
    
    @pytest.mark.asyncio
    async def test_handle_task_failure_valueerror(self, handler, sample_decision_task):
        """Test task failure handling for ValueError."""
        error = ValueError("Invalid workflow attributes")
        
        await handler.handle_task_failure(sample_decision_task, error)
        
        # Verify the correct failure cause was used
        call_args = handler._client.worker_stub.RespondDecisionTaskFailed.call_args[0][0]
        assert call_args.cause == DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_BAD_SCHEDULE_ACTIVITY_ATTRIBUTES
        assert call_args.task_token == sample_decision_task.task_token
        assert call_args.identity == handler._identity
    
    @pytest.mark.asyncio
    async def test_handle_task_failure_generic_error(self, handler, sample_decision_task):
        """Test task failure handling for generic error."""
        error = RuntimeError("Generic error")
        
        await handler.handle_task_failure(sample_decision_task, error)
        
        # Verify the default failure cause was used
        call_args = handler._client.worker_stub.RespondDecisionTaskFailed.call_args[0][0]
        assert call_args.cause == DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_UNHANDLED_DECISION
        assert call_args.task_token == sample_decision_task.task_token
        assert call_args.identity == handler._identity
    
    @pytest.mark.asyncio
    async def test_handle_task_failure_with_error_details(self, handler, sample_decision_task):
        """Test task failure handling includes error details."""
        error = ValueError("Test error message")
        
        await handler.handle_task_failure(sample_decision_task, error)
        
        call_args = handler._client.worker_stub.RespondDecisionTaskFailed.call_args[0][0]
        assert isinstance(call_args.details, Payload)
        assert call_args.details.data == b"Test error message"
    
    @pytest.mark.asyncio
    async def test_handle_task_failure_respond_error(self, handler, sample_decision_task):
        """Test task failure handling when respond fails."""
        error = ValueError("Test error")
        handler._client.worker_stub.RespondDecisionTaskFailed.side_effect = Exception("Respond failed")
        
        # Should not raise exception, but should log error
        with patch('cadence.worker._decision_task_handler.logger') as mock_logger:
            await handler.handle_task_failure(sample_decision_task, error)
            # Now uses logger.error with exc_info=True instead of logger.exception
            mock_logger.error.assert_called()
    
    @pytest.mark.asyncio
    async def test_respond_decision_task_completed_success(self, handler, sample_decision_task):
        """Test successful decision task completion response."""
        decision_result = Mock(spec=DecisionResult)
        decision_result.decisions = [Decision(), Decision()]
        
        await handler._respond_decision_task_completed(sample_decision_task, decision_result)
        
        # Verify the request was created correctly
        call_args = handler._client.worker_stub.RespondDecisionTaskCompleted.call_args[0][0]
        assert isinstance(call_args, RespondDecisionTaskCompletedRequest)
        assert call_args.task_token == sample_decision_task.task_token
        assert call_args.identity == handler._identity
        assert call_args.return_new_decision_task
        assert len(call_args.decisions) == 2
    
    @pytest.mark.asyncio
    async def test_respond_decision_task_completed_no_query_results(self, handler, sample_decision_task):
        """Test decision task completion response without query results."""
        decision_result = Mock(spec=DecisionResult)
        decision_result.decisions = []
        
        await handler._respond_decision_task_completed(sample_decision_task, decision_result)
        
        call_args = handler._client.worker_stub.RespondDecisionTaskCompleted.call_args[0][0]
        assert call_args.return_new_decision_task
        assert len(call_args.decisions) == 0
    
    @pytest.mark.asyncio
    async def test_respond_decision_task_completed_error(self, handler, sample_decision_task):
        """Test decision task completion response error handling."""
        decision_result = Mock(spec=DecisionResult)
        decision_result.decisions = []
        
        handler._client.worker_stub.RespondDecisionTaskCompleted.side_effect = Exception("Respond failed")
        
        with pytest.raises(Exception, match="Respond failed"):
            await handler._respond_decision_task_completed(sample_decision_task, decision_result)
    
    
    @pytest.mark.asyncio
    async def test_workflow_engine_creation_with_workflow_info(self, handler, sample_decision_task, mock_registry):
        """Test that WorkflowEngine is created with correct WorkflowInfo."""
        mock_workflow_func = Mock()
        mock_workflow_definition = Mock()
        mock_workflow_definition.fn = mock_workflow_func
        mock_registry.get_workflow.return_value = mock_workflow_definition

        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_engine.process_decision = AsyncMock(return_value=mock_decision_result)

        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine) as mock_workflow_engine_class:
            with patch('cadence.worker._decision_task_handler.WorkflowInfo') as mock_workflow_info_class:
                await handler._handle_task_implementation(sample_decision_task)

                # Verify WorkflowInfo was created with correct parameters (called once for engine)
                assert mock_workflow_info_class.call_count == 1
                for call in mock_workflow_info_class.call_args_list:
                    assert call[1] == {
                        'workflow_type': "TestWorkflow",
                        'workflow_domain': "test_domain",
                        'workflow_id': "test_workflow_id",
                        'workflow_run_id': "test_run_id"
                    }

                # Verify WorkflowEngine was created with correct parameters
                mock_workflow_engine_class.assert_called_once()
                call_args = mock_workflow_engine_class.call_args
                assert call_args[1]['info'] is not None
                assert call_args[1]['client'] == handler._client
                assert call_args[1]['workflow_func'] == mock_workflow_func
