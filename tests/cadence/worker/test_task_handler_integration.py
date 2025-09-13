#!/usr/bin/env python3
"""
Integration tests for task handlers.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, PropertyMock

from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.client import Client
from cadence.worker._decision_task_handler import DecisionTaskHandler
from cadence.worker._registry import Registry
from cadence._internal.workflow.workflow_engine import WorkflowEngine, DecisionResult


class TestTaskHandlerIntegration:
    """Integration tests for task handlers."""
    
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
        return task
    
    @pytest.mark.asyncio
    async def test_full_task_handling_flow_success(self, handler, sample_decision_task, mock_registry):
        """Test the complete task handling flow from base handler through decision handler."""
        # Mock workflow function
        mock_workflow_func = Mock()
        mock_registry.get_workflow.return_value = mock_workflow_func
        
        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_decision_result.force_create_new_decision_task = False
        mock_decision_result.query_results = {}
        mock_engine.process_decision = AsyncMock(return_value=mock_decision_result)
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine):
            # Use the base handler's handle_task method
            await handler.handle_task(sample_decision_task)
        
        # Verify the complete flow
        mock_registry.get_workflow.assert_called_once_with("TestWorkflow")
        mock_engine.process_decision.assert_called_once_with(sample_decision_task)
        handler._client.worker_stub.RespondDecisionTaskCompleted.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_full_task_handling_flow_with_error(self, handler, sample_decision_task, mock_registry):
        """Test the complete task handling flow when an error occurs."""
        # Mock workflow function
        mock_workflow_func = Mock()
        mock_registry.get_workflow.return_value = mock_workflow_func
        
        # Mock workflow engine to raise an error
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine.process_decision = AsyncMock(side_effect=RuntimeError("Workflow processing failed"))
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine):
            # Use the base handler's handle_task method
            await handler.handle_task(sample_decision_task)
        
        # Verify error handling
        handler._client.worker_stub.RespondDecisionTaskFailed.assert_called_once()
        call_args = handler._client.worker_stub.RespondDecisionTaskFailed.call_args[0][0]
        assert call_args.task_token == sample_decision_task.task_token
        assert call_args.identity == handler._identity
    
    @pytest.mark.asyncio
    async def test_context_propagation_integration(self, handler, sample_decision_task, mock_registry):
        """Test that context propagation works correctly in the integration."""
        # Mock workflow function
        mock_workflow_func = Mock()
        mock_registry.get_workflow.return_value = mock_workflow_func
        
        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_decision_result.force_create_new_decision_task = False
        mock_decision_result.query_results = {}
        mock_engine.process_decision = AsyncMock(return_value=mock_decision_result)
        
        # Track if context methods are called
        context_propagated = False
        context_unset = False
        
        async def track_propagate_context(task):
            nonlocal context_propagated
            context_propagated = True
        
        async def track_unset_current_context():
            nonlocal context_unset
            context_unset = True
        
        handler._propagate_context = track_propagate_context
        handler._unset_current_context = track_unset_current_context
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine):
            await handler.handle_task(sample_decision_task)
        
        # Verify context methods were called
        assert context_propagated
        assert context_unset
    
    @pytest.mark.asyncio
    async def test_multiple_workflow_executions(self, handler, mock_registry):
        """Test handling multiple workflow executions with different engines."""
        # Mock workflow function
        mock_workflow_func = Mock()
        mock_registry.get_workflow.return_value = mock_workflow_func
        
        # Create multiple decision tasks for different workflows
        task1 = Mock(spec=PollForDecisionTaskResponse)
        task1.task_token = b"task1_token"
        task1.workflow_execution = Mock()
        task1.workflow_execution.workflow_id = "workflow1"
        task1.workflow_execution.run_id = "run1"
        task1.workflow_type = Mock()
        task1.workflow_type.name = "TestWorkflow"
        
        task2 = Mock(spec=PollForDecisionTaskResponse)
        task2.task_token = b"task2_token"
        task2.workflow_execution = Mock()
        task2.workflow_execution.workflow_id = "workflow2"
        task2.workflow_execution.run_id = "run2"
        task2.workflow_type = Mock()
        task2.workflow_type.name = "TestWorkflow"
        
        # Mock workflow engines
        mock_engine1 = Mock(spec=WorkflowEngine)
        mock_engine2 = Mock(spec=WorkflowEngine)
        
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_decision_result.force_create_new_decision_task = False
        mock_decision_result.query_results = {}
        
        mock_engine1.process_decision = AsyncMock(return_value=mock_decision_result)
        mock_engine2.process_decision = AsyncMock(return_value=mock_decision_result)
        
        def mock_workflow_engine_creator(*args, **kwargs):
            # Return different engines based on workflow info
            workflow_info = kwargs.get('info')
            if workflow_info and workflow_info.workflow_id == "workflow1":
                return mock_engine1
            else:
                return mock_engine2
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', side_effect=mock_workflow_engine_creator):
            # Process both tasks
            await handler.handle_task(task1)
            await handler.handle_task(task2)
        
        # Verify both engines were created and used
        assert len(handler._workflow_engines) == 2
        assert "workflow1:run1" in handler._workflow_engines
        assert "workflow2:run2" in handler._workflow_engines
        
        # Verify both engines were called
        mock_engine1.process_decision.assert_called_once_with(task1)
        mock_engine2.process_decision.assert_called_once_with(task2)
    
    @pytest.mark.asyncio
    async def test_workflow_engine_cleanup_integration(self, handler, sample_decision_task, mock_registry):
        """Test workflow engine cleanup integration."""
        # Mock workflow function
        mock_workflow_func = Mock()
        mock_registry.get_workflow.return_value = mock_workflow_func
        
        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_decision_result.force_create_new_decision_task = False
        mock_decision_result.query_results = {}
        mock_engine.process_decision = AsyncMock(return_value=mock_decision_result)
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine):
            # Process task to create engine
            await handler.handle_task(sample_decision_task)
            
            # Verify engine was created
            assert len(handler._workflow_engines) == 1
            assert "test_workflow_id:test_run_id" in handler._workflow_engines
            
            # Clean up engine
            handler.cleanup_workflow_engine("test_workflow_id", "test_run_id")
            
            # Verify engine was cleaned up
            assert len(handler._workflow_engines) == 0
    
    @pytest.mark.asyncio
    async def test_error_handling_with_context_cleanup(self, handler, sample_decision_task, mock_registry):
        """Test that context cleanup happens even when errors occur."""
        # Mock workflow function
        mock_workflow_func = Mock()
        mock_registry.get_workflow.return_value = mock_workflow_func
        
        # Mock workflow engine to raise an error
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine.process_decision = AsyncMock(side_effect=RuntimeError("Workflow processing failed"))
        
        # Track context cleanup
        context_unset = False
        
        async def track_unset_current_context():
            nonlocal context_unset
            context_unset = True
        
        handler._unset_current_context = track_unset_current_context
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine):
            await handler.handle_task(sample_decision_task)
        
        # Verify context was cleaned up even after error
        assert context_unset
        
        # Verify error was handled
        handler._client.worker_stub.RespondDecisionTaskFailed.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_concurrent_task_handling(self, handler, mock_registry):
        """Test handling multiple tasks concurrently."""
        import asyncio
        
        # Mock workflow function
        mock_workflow_func = Mock()
        mock_registry.get_workflow.return_value = mock_workflow_func
        
        # Create multiple tasks
        tasks = []
        for i in range(3):
            task = Mock(spec=PollForDecisionTaskResponse)
            task.task_token = f"task{i}_token".encode()
            task.workflow_execution = Mock()
            task.workflow_execution.workflow_id = f"workflow{i}"
            task.workflow_execution.run_id = f"run{i}"
            task.workflow_type = Mock()
            task.workflow_type.name = "TestWorkflow"
            tasks.append(task)
        
        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_decision_result.force_create_new_decision_task = False
        mock_decision_result.query_results = {}
        mock_engine.process_decision = AsyncMock(return_value=mock_decision_result)
        
        with patch('cadence.worker._decision_task_handler.WorkflowEngine', return_value=mock_engine):
            # Process all tasks concurrently
            await asyncio.gather(*[handler.handle_task(task) for task in tasks])
        
        # Verify all tasks were processed
        assert mock_engine.process_decision.call_count == 3
        assert handler._client.worker_stub.RespondDecisionTaskCompleted.call_count == 3
        
        # Verify engines were created for each workflow
        assert len(handler._workflow_engines) == 3
