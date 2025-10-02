import pytest
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, PropertyMock

from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.service_workflow_pb2 import StartWorkflowExecutionRequest, StartWorkflowExecutionResponse
from cadence.api.v1.workflow_pb2 import WorkflowIdReusePolicy
from cadence.client import Client, StartWorkflowOptions, WorkflowRun
from cadence.data_converter import DefaultDataConverter


@pytest.fixture
def mock_client():
    """Create a mock client for testing."""
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="test-domain")
    type(client).identity = PropertyMock(return_value="test-identity")
    type(client).data_converter = PropertyMock(return_value=DefaultDataConverter())
    type(client).metrics_emitter = PropertyMock(return_value=None)

    # Mock the workflow stub
    workflow_stub = Mock()
    type(client).workflow_stub = PropertyMock(return_value=workflow_stub)

    return client


class TestStartWorkflowOptions:
    """Test StartWorkflowOptions dataclass."""

    def test_default_values(self):
        """Test default values for StartWorkflowOptions."""
        options = StartWorkflowOptions()
        assert options.workflow_id is None
        assert options.task_list == ""
        assert options.execution_start_to_close_timeout is None
        assert options.task_start_to_close_timeout is None
        assert options.workflow_id_reuse_policy == WorkflowIdReusePolicy.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE
        assert options.cron_schedule is None
        assert options.memo is None
        assert options.search_attributes is None

    def test_custom_values(self):
        """Test setting custom values for StartWorkflowOptions."""
        options = StartWorkflowOptions(
            workflow_id="custom-id",
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=30),
            task_start_to_close_timeout=timedelta(seconds=10),
            workflow_id_reuse_policy=WorkflowIdReusePolicy.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE,
            cron_schedule="0 * * * *",
            memo={"key": "value"},
            search_attributes={"attr": "value"}
        )

        assert options.workflow_id == "custom-id"
        assert options.task_list == "test-task-list"
        assert options.execution_start_to_close_timeout == timedelta(minutes=30)
        assert options.task_start_to_close_timeout == timedelta(seconds=10)
        assert options.workflow_id_reuse_policy == WorkflowIdReusePolicy.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE
        assert options.cron_schedule == "0 * * * *"
        assert options.memo == {"key": "value"}
        assert options.search_attributes == {"attr": "value"}


class TestWorkflowRun:
    """Test WorkflowRun class."""

    def test_properties(self, mock_client):
        """Test WorkflowRun properties."""
        execution = WorkflowExecution()
        execution.workflow_id = "test-workflow-id"
        execution.run_id = "test-run-id"

        workflow_run = WorkflowRun(execution=execution, client=mock_client)

        assert workflow_run.workflow_id == "test-workflow-id"
        assert workflow_run.run_id == "test-run-id"
        assert workflow_run.client is mock_client

    @pytest.mark.asyncio
    async def test_get_result_not_implemented(self, mock_client):
        """Test that get_result raises NotImplementedError."""
        execution = WorkflowExecution()
        execution.workflow_id = "test-workflow-id"
        execution.run_id = "test-run-id"

        workflow_run = WorkflowRun(execution=execution, client=mock_client)

        with pytest.raises(NotImplementedError, match="get_result not yet implemented"):
            await workflow_run.get_result()


class TestClientBuildStartWorkflowRequest:
    """Test Client._build_start_workflow_request method."""

    @pytest.mark.asyncio
    async def test_build_request_with_string_workflow(self, mock_client):
        """Test building request with string workflow name."""
        # Create real client instance to test the method
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            workflow_id="test-workflow-id",
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=30),
            task_start_to_close_timeout=timedelta(seconds=10)
        )

        request = await client._build_start_workflow_request("TestWorkflow", ("arg1", "arg2"), options)

        assert isinstance(request, StartWorkflowExecutionRequest)
        assert request.domain == "test-domain"
        assert request.workflow_id == "test-workflow-id"
        assert request.workflow_type.name == "TestWorkflow"
        assert request.task_list.name == "test-task-list"
        assert request.identity == client.identity
        assert request.workflow_id_reuse_policy == WorkflowIdReusePolicy.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE
        assert request.request_id != ""  # Should be a UUID

        # Verify UUID format
        uuid.UUID(request.request_id)  # This will raise if not valid UUID

    @pytest.mark.asyncio
    async def test_build_request_with_callable_workflow(self, mock_client):
        """Test building request with callable workflow."""
        def test_workflow():
            pass

        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list"
        )

        request = await client._build_start_workflow_request(test_workflow, (), options)

        assert request.workflow_type.name == "test_workflow"

    @pytest.mark.asyncio
    async def test_build_request_generates_workflow_id(self, mock_client):
        """Test that workflow_id is generated when not provided."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(task_list="test-task-list")

        request = await client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.workflow_id != ""
        # Verify it's a valid UUID
        uuid.UUID(request.workflow_id)

    @pytest.mark.asyncio
    async def test_build_request_missing_task_list(self, mock_client):
        """Test that missing task_list raises ValueError."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions()  # No task_list

        with pytest.raises(ValueError, match="task_list is required"):
            await client._build_start_workflow_request("TestWorkflow", (), options)

    @pytest.mark.asyncio
    async def test_build_request_with_input_args(self, mock_client):
        """Test building request with input arguments."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(task_list="test-task-list")

        request = await client._build_start_workflow_request("TestWorkflow", ("arg1", 42, {"key": "value"}), options)

        # Should have input payload
        assert request.HasField("input")
        assert len(request.input.data) > 0

    @pytest.mark.asyncio
    async def test_build_request_with_timeouts(self, mock_client):
        """Test building request with timeout settings."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=30),
            task_start_to_close_timeout=timedelta(seconds=10)
        )

        request = await client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.HasField("execution_start_to_close_timeout")
        assert request.HasField("task_start_to_close_timeout")

        # Check timeout values (30 minutes = 1800 seconds)
        assert request.execution_start_to_close_timeout.seconds == 1800
        assert request.task_start_to_close_timeout.seconds == 10

    @pytest.mark.asyncio
    async def test_build_request_with_cron_schedule(self, mock_client):
        """Test building request with cron schedule."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            cron_schedule="0 * * * *"
        )

        request = await client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.cron_schedule == "0 * * * *"


class TestClientStartWorkflow:
    """Test Client.start_workflow method."""

    @pytest.mark.asyncio
    async def test_start_workflow_success(self, mock_client):
        """Test successful workflow start."""
        # Setup mock response
        response = StartWorkflowExecutionResponse()
        response.run_id = "test-run-id"

        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(return_value=response)

        # Create a real client but replace the workflow_stub
        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        # Mock the internal method to avoid full request building
        async def mock_build_request(workflow, args, options):
            request = StartWorkflowExecutionRequest()
            request.workflow_id = "test-workflow-id"
            request.domain = "test-domain"
            return request

        client._build_start_workflow_request = AsyncMock(side_effect=mock_build_request)

        execution = await client.start_workflow(
            "TestWorkflow",
            "arg1", "arg2",
            task_list="test-task-list",
            workflow_id="test-workflow-id"
        )

        assert isinstance(execution, WorkflowExecution)
        assert execution.workflow_id == "test-workflow-id"
        assert execution.run_id == "test-run-id"

        # Verify the gRPC call was made
        mock_client.workflow_stub.StartWorkflowExecution.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_workflow_grpc_error(self, mock_client):
        """Test workflow start with gRPC error."""
        # Setup mock to raise exception
        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(side_effect=Exception("gRPC error"))

        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        # Mock the internal method
        client._build_start_workflow_request = AsyncMock(return_value=StartWorkflowExecutionRequest())

        with pytest.raises(Exception, match="Failed to start workflow: gRPC error"):
            await client.start_workflow(
                "TestWorkflow",
                task_list="test-task-list"
            )

    @pytest.mark.asyncio
    async def test_start_workflow_with_kwargs(self, mock_client):
        """Test start_workflow with options as kwargs."""
        response = StartWorkflowExecutionResponse()
        response.run_id = "test-run-id"

        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(return_value=response)

        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        # Mock the internal method to capture options
        captured_options = None
        async def mock_build_request(workflow, args, options):
            nonlocal captured_options
            captured_options = options
            request = StartWorkflowExecutionRequest()
            request.workflow_id = "test-workflow-id"
            return request

        client._build_start_workflow_request = AsyncMock(side_effect=mock_build_request)

        await client.start_workflow(
            "TestWorkflow",
            "arg1",
            task_list="test-task-list",
            workflow_id="custom-id",
            execution_start_to_close_timeout=timedelta(minutes=30)
        )

        # Verify options were properly constructed
        assert captured_options.task_list == "test-task-list"
        assert captured_options.workflow_id == "custom-id"
        assert captured_options.execution_start_to_close_timeout == timedelta(minutes=30)


class TestClientExecuteWorkflow:
    """Test Client.execute_workflow method."""

    @pytest.mark.asyncio
    async def test_execute_workflow_success(self, mock_client):
        """Test successful workflow execution."""
        # Mock start_workflow to return execution
        execution = WorkflowExecution()
        execution.workflow_id = "test-workflow-id"
        execution.run_id = "test-run-id"

        client = Client(domain="test-domain", target="localhost:7933")
        client.start_workflow = AsyncMock(return_value=execution)

        workflow_run = await client.execute_workflow(
            "TestWorkflow",
            "arg1", "arg2",
            task_list="test-task-list"
        )

        assert isinstance(workflow_run, WorkflowRun)
        assert workflow_run.execution is execution
        assert workflow_run.client is client
        assert workflow_run.workflow_id == "test-workflow-id"
        assert workflow_run.run_id == "test-run-id"

        # Verify start_workflow was called with correct arguments
        client.start_workflow.assert_called_once_with(
            "TestWorkflow",
            "arg1", "arg2",
            task_list="test-task-list"
        )

    @pytest.mark.asyncio
    async def test_execute_workflow_propagates_error(self, mock_client):
        """Test that execute_workflow propagates errors from start_workflow."""
        client = Client(domain="test-domain", target="localhost:7933")
        client.start_workflow = AsyncMock(side_effect=ValueError("Invalid task_list"))

        with pytest.raises(ValueError, match="Invalid task_list"):
            await client.execute_workflow(
                "TestWorkflow",
                task_list=""
            )


@pytest.mark.asyncio
async def test_integration_workflow_invocation():
    """Integration test for workflow invocation flow."""
    # This test verifies the complete flow works together
    response = StartWorkflowExecutionResponse()
    response.run_id = "integration-run-id"

    # Create client with mocked gRPC stub
    client = Client(domain="test-domain", target="localhost:7933")
    client._workflow_stub = Mock()
    client._workflow_stub.StartWorkflowExecution = AsyncMock(return_value=response)

    # Test the complete flow
    workflow_run = await client.execute_workflow(
        "IntegrationTestWorkflow",
        "test-arg",
        42,
        {"data": "value"},
        task_list="integration-task-list",
        workflow_id="integration-workflow-id",
        execution_start_to_close_timeout=timedelta(minutes=10)
    )

    # Verify result
    assert workflow_run.workflow_id == "integration-workflow-id"
    assert workflow_run.run_id == "integration-run-id"

    # Verify the gRPC call was made with proper request
    client._workflow_stub.StartWorkflowExecution.assert_called_once()
    request = client._workflow_stub.StartWorkflowExecution.call_args[0][0]

    assert request.domain == "test-domain"
    assert request.workflow_id == "integration-workflow-id"
    assert request.workflow_type.name == "IntegrationTestWorkflow"
    assert request.task_list.name == "integration-task-list"
    assert request.HasField("input")  # Should have encoded input
    assert request.HasField("execution_start_to_close_timeout")