import pytest
from contextlib import contextmanager
from unittest.mock import Mock, AsyncMock, patch, PropertyMock

from cadence.api.v1.history_pb2 import History
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.client import Client
from cadence.worker._decision_task_handler import DecisionTaskHandler
from cadence.worker._registry import Registry
from cadence._internal.workflow.workflow_engine import WorkflowEngine, DecisionResult
from cadence import workflow
from cadence.workflow import WorkflowDefinition, WorkflowDefinitionOptions


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
            identity="test_identity",
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
        task.history = History()
        task.next_page_token = b""
        return task

    @pytest.mark.asyncio
    async def test_full_task_handling_flow_success(
        self, handler, sample_decision_task, mock_registry
    ):
        """Test the complete task handling flow from base handler through decision handler."""
        # Create actual workflow definition

        class MockWorkflow:
            @workflow.run
            async def run(self):
                return "test_result"

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(MockWorkflow, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition

        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_engine.process_decision = Mock(return_value=mock_decision_result)

        with patch(
            "cadence.worker._decision_task_handler.WorkflowEngine",
            return_value=mock_engine,
        ):
            # Use the base handler's handle_task method
            await handler.handle_task(sample_decision_task)

        # Verify the complete flow
        mock_registry.get_workflow.assert_called_once_with("TestWorkflow")
        mock_engine.process_decision.assert_called_once_with(
            sample_decision_task.history.events
        )
        handler._client.worker_stub.RespondDecisionTaskCompleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_task_handling_flow_with_error(
        self, handler, sample_decision_task, mock_registry
    ):
        """Test the complete task handling flow when an error occurs."""

        # Create actual workflow definition
        class MockWorkflow:
            @workflow.run
            async def run(self):
                return "test_result"

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(MockWorkflow, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition

        # Mock workflow engine to raise an error
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_engine.process_decision = Mock(
            side_effect=RuntimeError("Workflow processing failed")
        )

        with patch(
            "cadence.worker._decision_task_handler.WorkflowEngine",
            return_value=mock_engine,
        ):
            # Use the base handler's handle_task method
            await handler.handle_task(sample_decision_task)

        # Verify error handling
        handler._client.worker_stub.RespondDecisionTaskFailed.assert_called_once()
        call_args = handler._client.worker_stub.RespondDecisionTaskFailed.call_args[0][
            0
        ]
        assert call_args.task_token == sample_decision_task.task_token
        assert call_args.identity == handler._identity

    @pytest.mark.asyncio
    async def test_context_activation_integration(
        self, handler, sample_decision_task, mock_registry
    ):
        """Test that context activation works correctly in the integration."""

        # Create actual workflow definition
        class MockWorkflow:
            @workflow.run
            async def run(self):
                return "test_result"

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(MockWorkflow, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition

        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_engine.process_decision = Mock(return_value=mock_decision_result)

        # Track if context is activated
        context_activated = False

        def track_context_activation():
            nonlocal context_activated
            context_activated = True

        with patch(
            "cadence.worker._decision_task_handler.WorkflowEngine",
            return_value=mock_engine,
        ):
            with patch(
                "cadence._internal.workflow.workflow_engine.Context"
            ) as mock_context_class:
                mock_context = Mock()
                mock_context._activate = Mock(
                    return_value=contextmanager(lambda: track_context_activation())()
                )
                mock_context_class.return_value = mock_context

                await handler.handle_task(sample_decision_task)

        # Verify context was activated
        assert context_activated

    @pytest.mark.asyncio
    async def test_multiple_workflow_executions(self, handler, mock_registry):
        """Test handling multiple workflow executions creates new engines for each."""

        # Create actual workflow definition
        class MockWorkflow:
            @workflow.run
            async def run(self):
                return "test_result"

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(MockWorkflow, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition

        # Create multiple decision tasks for different workflows
        task1 = Mock(spec=PollForDecisionTaskResponse)
        task1.task_token = b"task1_token"
        task1.workflow_execution = Mock()
        task1.workflow_execution.workflow_id = "workflow1"
        task1.workflow_execution.run_id = "run1"
        task1.workflow_type = Mock()
        task1.workflow_type.name = "TestWorkflow"
        task1.started_event_id = 1
        task1.attempt = 1
        task1.history = History()
        task1.next_page_token = b""

        task2 = Mock(spec=PollForDecisionTaskResponse)
        task2.task_token = b"task2_token"
        task2.workflow_execution = Mock()
        task2.workflow_execution.workflow_id = "workflow2"
        task2.workflow_execution.run_id = "run2"
        task2.workflow_type = Mock()
        task2.workflow_type.name = "TestWorkflow"
        task2.started_event_id = 2
        task2.attempt = 1
        task2.history = History()
        task2.next_page_token = b""
        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute

        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []

        mock_engine.process_decision = Mock(return_value=mock_decision_result)

        with patch(
            "cadence.worker._decision_task_handler.WorkflowEngine",
            return_value=mock_engine,
        ) as mock_engine_class:
            # Process both tasks
            await handler.handle_task(task1)
            await handler.handle_task(task2)

        # Verify engines were created for each task
        assert mock_engine_class.call_count == 2

        # Verify both tasks were processed
        assert mock_engine.process_decision.call_count == 2

    @pytest.mark.asyncio
    async def test_workflow_engine_creation_integration(
        self, handler, sample_decision_task, mock_registry
    ):
        """Test workflow engine creation integration."""

        # Create actual workflow definition
        class MockWorkflow:
            @workflow.run
            async def run(self):
                return "test_result"

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(MockWorkflow, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition

        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_engine.process_decision = Mock(return_value=mock_decision_result)

        with patch(
            "cadence.worker._decision_task_handler.WorkflowEngine",
            return_value=mock_engine,
        ) as mock_engine_class:
            # Process task to create engine
            await handler.handle_task(sample_decision_task)

            # Verify engine was created and used
            mock_engine_class.assert_called_once()
            mock_engine.process_decision.assert_called_once_with(
                sample_decision_task.history.events
            )

    @pytest.mark.asyncio
    async def test_error_handling_with_context_cleanup(
        self, handler, sample_decision_task, mock_registry
    ):
        """Test that context cleanup happens even when errors occur."""

        # Create actual workflow definition
        class MockWorkflow:
            @workflow.run
            async def run(self):
                return "test_result"

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(MockWorkflow, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition

        # Mock workflow engine to raise an error
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_engine.process_decision = Mock(
            side_effect=RuntimeError("Workflow processing failed")
        )

        # Track context cleanup
        context_cleaned_up = False

        def track_context_cleanup():
            nonlocal context_cleaned_up
            context_cleaned_up = True

        with patch(
            "cadence.worker._decision_task_handler.WorkflowEngine",
            return_value=mock_engine,
        ):
            with patch(
                "cadence._internal.workflow.workflow_engine.Context"
            ) as mock_context_class:
                mock_context = Mock()
                mock_context._activate = Mock(
                    return_value=contextmanager(lambda: track_context_cleanup())()
                )
                mock_context_class.return_value = mock_context

                await handler.handle_task(sample_decision_task)

        # Verify context was cleaned up even after error
        assert context_cleaned_up

        # Verify error was handled
        handler._client.worker_stub.RespondDecisionTaskFailed.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_task_handling(self, handler, mock_registry):
        """Test handling multiple tasks concurrently."""
        import asyncio

        # Create actual workflow definition
        class MockWorkflow:
            @workflow.run
            async def run(self):
                return "test_result"

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(MockWorkflow, workflow_opts)
        mock_registry.get_workflow.return_value = workflow_definition

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
            task.started_event_id = i + 1
            task.attempt = 1
            tasks.append(task)
            task.history = History()
            task.next_page_token = b""

        # Mock workflow engine
        mock_engine = Mock(spec=WorkflowEngine)
        mock_engine._is_workflow_complete = False  # Add missing attribute
        mock_decision_result = Mock(spec=DecisionResult)
        mock_decision_result.decisions = []
        mock_engine.process_decision = Mock(return_value=mock_decision_result)

        with patch(
            "cadence.worker._decision_task_handler.WorkflowEngine",
            return_value=mock_engine,
        ):
            # Process all tasks concurrently
            await asyncio.gather(*[handler.handle_task(task) for task in tasks])

        # Verify all tasks were processed
        assert mock_engine.process_decision.call_count == 3
        assert handler._client.worker_stub.RespondDecisionTaskCompleted.call_count == 3
