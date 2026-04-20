import pytest
import uuid
from datetime import timedelta, datetime, timezone
from unittest.mock import AsyncMock, Mock, PropertyMock

from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.service_workflow_pb2 import (
    StartWorkflowExecutionRequest,
    StartWorkflowExecutionResponse,
)
from cadence.client import (
    Client,
    StartWorkflowOptions,
    _validate_and_apply_defaults,
)
from cadence.api.v1 import workflow_pb2
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowDefinition, WorkflowDefinitionOptions


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
    """Test StartWorkflowOptions TypedDict and validation."""

    def test_default_values(self):
        """Test default values for StartWorkflowOptions."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
        )
        assert options.get("workflow_id") is None
        assert options["task_list"] == "test-task-list"
        assert options["execution_start_to_close_timeout"] == timedelta(minutes=10)
        assert options["task_start_to_close_timeout"] == timedelta(seconds=30)
        assert options.get("cron_schedule") is None

    def test_custom_values(self):
        """Test setting custom values for StartWorkflowOptions."""
        options = StartWorkflowOptions(
            workflow_id="custom-id",
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=30),
            task_start_to_close_timeout=timedelta(seconds=10),
            cron_schedule="0 * * * *",
        )

        assert options["workflow_id"] == "custom-id"
        assert options["task_list"] == "test-task-list"
        assert options["execution_start_to_close_timeout"] == timedelta(minutes=30)
        assert options["task_start_to_close_timeout"] == timedelta(seconds=10)
        assert options["cron_schedule"] == "0 * * * *"


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
            task_start_to_close_timeout=timedelta(seconds=10),
        )

        request = client._build_start_workflow_request(
            "TestWorkflow", ("arg1", "arg2"), options
        )

        assert isinstance(request, StartWorkflowExecutionRequest)
        assert request.domain == "test-domain"
        assert request.workflow_id == "test-workflow-id"
        assert request.workflow_type.name == "TestWorkflow"
        assert request.task_list.name == "test-task-list"
        assert request.identity == client.identity
        assert (
            request.workflow_id_reuse_policy == 0
        )  # Default protobuf value when not set
        assert request.request_id != ""  # Should be a UUID

        # Verify UUID format
        uuid.UUID(request.request_id)  # This will raise if not valid UUID

    @pytest.mark.asyncio
    async def test_build_request_with_workflow_definition(self, mock_client):
        """Test building request with WorkflowDefinition."""
        from cadence import workflow

        class TestWorkflow:
            @workflow.run
            async def run(self):
                pass

        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        workflow_definition = WorkflowDefinition.wrap(TestWorkflow, workflow_opts)

        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
        )

        request = client._build_start_workflow_request(workflow_definition, (), options)

        assert request.workflow_type.name == "test_workflow"

    @pytest.mark.asyncio
    async def test_build_request_generates_workflow_id(self, mock_client):
        """Test that workflow_id is generated when not provided."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
        )

        request = client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.workflow_id != ""
        # Verify it's a valid UUID
        uuid.UUID(request.workflow_id)

    def test_missing_task_list_raises_error(self):
        """Test that missing task_list raises ValueError."""
        options = StartWorkflowOptions()
        with pytest.raises(ValueError, match="task_list is required"):
            _validate_and_apply_defaults(options)

    def test_missing_execution_timeout_raises_error(self):
        """Test that missing execution_start_to_close_timeout raises ValueError."""
        options = StartWorkflowOptions(task_list="test-task-list")
        with pytest.raises(
            ValueError, match="execution_start_to_close_timeout is required"
        ):
            _validate_and_apply_defaults(options)

    def test_only_execution_timeout(self):
        """Test that only execution_start_to_close_timeout works with default task timeout."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
        )
        validated_options = _validate_and_apply_defaults(options)
        assert validated_options["execution_start_to_close_timeout"] == timedelta(
            minutes=10
        )
        assert validated_options["task_start_to_close_timeout"] == timedelta(
            seconds=10
        )  # Default applied

    def test_default_task_timeout(self):
        """Test that task_start_to_close_timeout defaults to 10 seconds when not provided."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=5),
        )
        validated_options = _validate_and_apply_defaults(options)
        assert validated_options["task_start_to_close_timeout"] == timedelta(seconds=10)

    def test_only_task_timeout(self):
        """Test that only task_start_to_close_timeout raises ValueError (execution timeout required)."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            task_start_to_close_timeout=timedelta(seconds=30),
        )
        with pytest.raises(
            ValueError, match="execution_start_to_close_timeout is required"
        ):
            _validate_and_apply_defaults(options)

    @pytest.mark.asyncio
    async def test_build_request_with_input_args(self, mock_client):
        """Test building request with input arguments."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
        )

        request = client._build_start_workflow_request(
            "TestWorkflow", ("arg1", 42, {"key": "value"}), options
        )

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
            task_start_to_close_timeout=timedelta(seconds=10),
        )

        request = client._build_start_workflow_request("TestWorkflow", (), options)

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
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
            cron_schedule="0 * * * *",
        )

        request = client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.cron_schedule == "0 * * * *"

    @pytest.mark.asyncio
    async def test_build_request_with_delay_start(self, mock_client):
        """Test building request with delay_start."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
            delay_start=timedelta(minutes=5),
        )

        request = client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.HasField("delay_start")
        assert request.delay_start.seconds == 300  # 5 minutes

    @pytest.mark.asyncio
    async def test_build_request_with_jitter_start(self, mock_client):
        """Test building request with jitter_start."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
            jitter_start=timedelta(seconds=30),
        )

        request = client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.HasField("jitter_start")
        assert request.jitter_start.seconds == 30

    @pytest.mark.asyncio
    async def test_build_request_with_delay_and_jitter_start(self, mock_client):
        """Test building request with both delay_start and jitter_start."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
            delay_start=timedelta(minutes=1),
            jitter_start=timedelta(seconds=10),
        )

        request = client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.delay_start.seconds == 60
        assert request.jitter_start.seconds == 10

    def test_negative_delay_start_raises_error(self):
        """Test that negative delay_start raises ValueError."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            delay_start=timedelta(seconds=-1),
        )
        with pytest.raises(ValueError, match="delay_start cannot be negative"):
            _validate_and_apply_defaults(options)

    def test_negative_jitter_start_raises_error(self):
        """Test that negative jitter_start raises ValueError."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            jitter_start=timedelta(seconds=-1),
        )
        with pytest.raises(ValueError, match="jitter_start cannot be negative"):
            _validate_and_apply_defaults(options)

    def test_zero_delay_start_is_valid(self):
        """Test that zero delay_start is valid."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            delay_start=timedelta(0),
        )
        validated = _validate_and_apply_defaults(options)
        assert validated["delay_start"] == timedelta(0)

    @pytest.mark.asyncio
    async def test_build_request_with_cron_overlap_policy_enum(self, mock_client):
        """Test building request with cron_overlap_policy as enum."""
        client = Client(domain="test-domain", target="localhost:7933")

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
            cron_schedule="0 * * * *",
            cron_overlap_policy=workflow_pb2.CRON_OVERLAP_POLICY_SKIPPED,
        )

        request = client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.cron_overlap_policy == workflow_pb2.CRON_OVERLAP_POLICY_SKIPPED

    @pytest.mark.asyncio
    async def test_build_request_with_first_run_at_timezone_aware(self, mock_client):
        """Test building request with timezone-aware first_run_at."""
        client = Client(domain="test-domain", target="localhost:7933")

        first_run = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
            cron_schedule="0 * * * *",
            first_run_at=first_run,
        )

        request = client._build_start_workflow_request("TestWorkflow", (), options)

        assert request.HasField("first_run_at")
        # Convert back and verify
        result_dt = request.first_run_at.ToDatetime()
        assert result_dt == first_run.replace(
            tzinfo=None
        )  # ToDatetime returns naive UTC

    def test_first_run_at_naive_datetime_raises_error(self):
        """Test that timezone-naive first_run_at raises ValueError."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            first_run_at=datetime(2024, 1, 1, 12, 0, 0),  # Naive
        )
        with pytest.raises(ValueError, match="must be timezone-aware"):
            _validate_and_apply_defaults(options)

    def test_first_run_at_aware_datetime_is_valid(self):
        """Test that timezone-aware first_run_at is valid."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            first_run_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        # Should not raise
        validated = _validate_and_apply_defaults(options)
        assert validated["first_run_at"] == datetime(
            2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc
        )

    def test_first_run_at_before_epoch_raises_error(self):
        """Test that first_run_at before Unix epoch raises ValueError."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            first_run_at=datetime(1960, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        with pytest.raises(ValueError, match="cannot be before Unix epoch"):
            _validate_and_apply_defaults(options)

    def test_first_run_at_at_epoch_is_valid(self):
        """Test that first_run_at exactly at Unix epoch is valid."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            first_run_at=datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        # Should not raise
        validated = _validate_and_apply_defaults(options)
        assert validated["first_run_at"] == datetime(
            1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc
        )

    @pytest.mark.parametrize(
        "policy",
        [
            workflow_pb2.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE_FAILED_ONLY,
            workflow_pb2.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE,
            workflow_pb2.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE,
            workflow_pb2.WORKFLOW_ID_REUSE_POLICY_TERMINATE_IF_RUNNING,
        ],
        ids=[
            "allow_duplicate_failed_only",
            "allow_duplicate",
            "reject_duplicate",
            "terminate_if_running",
        ],
    )
    def test_build_request_propagates_workflow_id_reuse_policy(
        self, policy: workflow_pb2.WorkflowIdReusePolicy
    ) -> None:
        """Non-INVALID reuse policies propagate through the builder."""
        client = Client(domain="test-domain", target="localhost:7933")
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
            workflow_id_reuse_policy=policy,
        )
        request = client._build_start_workflow_request("TestWorkflow", (), options)
        assert request.workflow_id_reuse_policy == policy

    def test_invalid_workflow_id_reuse_policy_raises_error(self):
        """Explicit WORKFLOW_ID_REUSE_POLICY_INVALID is rejected."""
        options = StartWorkflowOptions(
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            workflow_id_reuse_policy=workflow_pb2.WORKFLOW_ID_REUSE_POLICY_INVALID,
        )
        with pytest.raises(
            ValueError,
            match="workflow_id_reuse_policy cannot be WORKFLOW_ID_REUSE_POLICY_INVALID",
        ):
            _validate_and_apply_defaults(options)


class TestClientStartWorkflow:
    """Test Client.start_workflow method."""

    @pytest.mark.asyncio
    async def test_start_workflow_success(self, mock_client):
        """Test successful workflow start."""
        # Setup mock response
        response = StartWorkflowExecutionResponse()
        response.run_id = "test-run-id"

        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(
            return_value=response
        )

        # Create a real client but replace the workflow_stub
        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        # Mock the internal method to avoid full request building
        def mock_build_request(workflow, args, options):
            request = StartWorkflowExecutionRequest()
            request.workflow_id = "test-workflow-id"
            request.domain = "test-domain"
            return request

        client._build_start_workflow_request = Mock(side_effect=mock_build_request)  # type: ignore

        execution = await client.start_workflow(
            "TestWorkflow",
            "arg1",
            "arg2",
            task_list="test-task-list",
            workflow_id="test-workflow-id",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
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
        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(
            side_effect=Exception("gRPC error")
        )

        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        # Mock the internal method
        client._build_start_workflow_request = Mock(  # type: ignore
            return_value=StartWorkflowExecutionRequest()
        )

        with pytest.raises(Exception, match="gRPC error"):
            await client.start_workflow(
                "TestWorkflow",
                task_list="test-task-list",
                execution_start_to_close_timeout=timedelta(minutes=10),
                task_start_to_close_timeout=timedelta(seconds=30),
            )

    @pytest.mark.asyncio
    async def test_start_workflow_with_kwargs(self, mock_client):
        """Test start_workflow with options as kwargs."""
        response = StartWorkflowExecutionResponse()
        response.run_id = "test-run-id"

        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(
            return_value=response
        )

        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        # Mock the internal method to capture options
        captured_options: StartWorkflowOptions = StartWorkflowOptions()

        def mock_build_request(workflow, args, options):
            nonlocal captured_options
            captured_options = options
            request = StartWorkflowExecutionRequest()
            request.workflow_id = "test-workflow-id"
            return request

        client._build_start_workflow_request = Mock(side_effect=mock_build_request)  # type: ignore

        await client.start_workflow(
            "TestWorkflow",
            "arg1",
            task_list="test-task-list",
            workflow_id="custom-id",
            execution_start_to_close_timeout=timedelta(minutes=30),
            task_start_to_close_timeout=timedelta(seconds=30),
        )

        # Verify options were properly constructed
        assert captured_options["task_list"] == "test-task-list"
        assert captured_options["workflow_id"] == "custom-id"
        assert captured_options["execution_start_to_close_timeout"] == timedelta(
            minutes=30
        )

    @pytest.mark.asyncio
    async def test_start_workflow_with_default_task_timeout(self, mock_client):
        """Test start_workflow uses default task timeout when not provided."""
        response = StartWorkflowExecutionResponse()
        response.run_id = "test-run-id"

        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(
            return_value=response
        )

        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        # Mock the internal method to capture options
        captured_options: StartWorkflowOptions = StartWorkflowOptions()

        def mock_build_request(workflow, args, options):
            nonlocal captured_options
            captured_options = options
            request = StartWorkflowExecutionRequest()
            request.workflow_id = "test-workflow-id"
            return request

        client._build_start_workflow_request = Mock(side_effect=mock_build_request)  # type: ignore

        await client.start_workflow(
            "TestWorkflow",
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            # No task_start_to_close_timeout provided - should use default
        )

        # Verify default was applied
        assert captured_options["task_start_to_close_timeout"] == timedelta(seconds=10)

    @pytest.mark.asyncio
    async def test_start_workflow_defaults_reuse_policy_to_allow_duplicate_failed_only(
        self, mock_client
    ):
        """start_workflow defaults workflow_id_reuse_policy to ALLOW_DUPLICATE_FAILED_ONLY."""
        response = StartWorkflowExecutionResponse()
        response.run_id = "test-run-id"

        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(
            return_value=response
        )

        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        await client.start_workflow(
            "TestWorkflow",
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
        )

        request = mock_client.workflow_stub.StartWorkflowExecution.call_args[0][0]
        assert (
            request.workflow_id_reuse_policy
            == workflow_pb2.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE_FAILED_ONLY
        )

    @pytest.mark.asyncio
    async def test_start_workflow_respects_explicit_reuse_policy(self, mock_client):
        """Explicit workflow_id_reuse_policy on start_workflow overrides the default."""
        response = StartWorkflowExecutionResponse()
        response.run_id = "test-run-id"

        mock_client.workflow_stub.StartWorkflowExecution = AsyncMock(
            return_value=response
        )

        client = Client(domain="test-domain", target="localhost:7933")
        client._workflow_stub = mock_client.workflow_stub

        await client.start_workflow(
            "TestWorkflow",
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=10),
            task_start_to_close_timeout=timedelta(seconds=30),
            workflow_id_reuse_policy=workflow_pb2.WORKFLOW_ID_REUSE_POLICY_TERMINATE_IF_RUNNING,
        )

        request = mock_client.workflow_stub.StartWorkflowExecution.call_args[0][0]
        assert (
            request.workflow_id_reuse_policy
            == workflow_pb2.WORKFLOW_ID_REUSE_POLICY_TERMINATE_IF_RUNNING
        )

    @pytest.mark.asyncio
    async def test_start_workflow_rejects_invalid_reuse_policy(self, mock_client):
        """Explicit WORKFLOW_ID_REUSE_POLICY_INVALID on start_workflow raises ValueError."""
        client = Client(domain="test-domain", target="localhost:7933")

        with pytest.raises(
            ValueError,
            match="workflow_id_reuse_policy cannot be WORKFLOW_ID_REUSE_POLICY_INVALID",
        ):
            await client.start_workflow(
                "TestWorkflow",
                task_list="test-task-list",
                execution_start_to_close_timeout=timedelta(minutes=10),
                task_start_to_close_timeout=timedelta(seconds=30),
                workflow_id_reuse_policy=workflow_pb2.WORKFLOW_ID_REUSE_POLICY_INVALID,
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
    execution = await client.start_workflow(
        "IntegrationTestWorkflow",
        "test-arg",
        42,
        {"data": "value"},
        task_list="integration-task-list",
        workflow_id="integration-workflow-id",
        execution_start_to_close_timeout=timedelta(minutes=10),
        task_start_to_close_timeout=timedelta(seconds=30),
    )

    # Verify result
    assert execution.workflow_id == "integration-workflow-id"
    assert execution.run_id == "integration-run-id"

    # Verify the gRPC call was made with proper request
    client._workflow_stub.StartWorkflowExecution.assert_called_once()
    request = client._workflow_stub.StartWorkflowExecution.call_args[0][0]

    assert request.domain == "test-domain"
    assert request.workflow_id == "integration-workflow-id"
    assert request.workflow_type.name == "IntegrationTestWorkflow"
    assert request.task_list.name == "integration-task-list"
    assert request.HasField("input")  # Should have encoded input
    assert request.HasField("execution_start_to_close_timeout")
