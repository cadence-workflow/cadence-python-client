import pytest
from datetime import timedelta

from cadence.api.v1 import workflow_pb2
from cadence.api.v1.service_domain_pb2 import (
    DescribeDomainRequest,
    DescribeDomainResponse,
)
from cadence.error import (
    EntityNotExistsError,
    WorkflowExecutionAlreadyStartedError,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME
from cadence.api.v1.service_workflow_pb2 import (
    DescribeWorkflowExecutionRequest,
    GetWorkflowExecutionHistoryRequest,
    TerminateWorkflowExecutionRequest,
)
from cadence.api.v1.common_pb2 import WorkflowExecution


@pytest.mark.usefixtures("helper")
async def test_domain_exists(helper: CadenceHelper):
    async with helper.client() as client:
        response: DescribeDomainResponse = await client.domain_stub.DescribeDomain(
            DescribeDomainRequest(name=DOMAIN_NAME)
        )
        assert response.domain.name == DOMAIN_NAME


@pytest.mark.usefixtures("helper")
async def test_domain_not_exists(helper: CadenceHelper):
    with pytest.raises(EntityNotExistsError):
        async with helper.client() as client:
            await client.domain_stub.DescribeDomain(
                DescribeDomainRequest(name="unknown-domain")
            )


# Worker Stub Tests


@pytest.mark.usefixtures("helper")
async def test_worker_stub_accessible(helper: CadenceHelper):
    """Test that worker_stub is properly initialized and accessible."""
    async with helper.client() as client:
        assert client.worker_stub is not None
        # Verify it's the correct type
        from cadence.api.v1.service_worker_pb2_grpc import WorkerAPIStub

        assert isinstance(client.worker_stub, WorkerAPIStub)


# Workflow Stub Tests


@pytest.mark.usefixtures("helper")
async def test_workflow_stub_start_and_describe(helper: CadenceHelper):
    """Comprehensive test for workflow start and describe operations.
    This integration test verifies:
    1. Starting a workflow execution via workflow_stub
    2. Describing the workflow execution
    3. All parameters match between start request and describe response:
       - workflow_id and run_id
       - workflow type
       - task list configuration
       - execution and task timeouts
    """
    async with helper.client() as client:
        # Define workflow parameters
        workflow_type = "test-workflow-type-describe"
        task_list_name = "test-task-list-describe"
        workflow_id = "test-workflow-describe-456"
        execution_timeout = timedelta(minutes=5)
        task_timeout = timedelta(seconds=10)  # Default value

        # Start a workflow with specific parameters
        execution = await client.start_workflow(
            workflow_type,
            task_list=task_list_name,
            execution_start_to_close_timeout=execution_timeout,
            task_start_to_close_timeout=task_timeout,
            workflow_id=workflow_id,
        )

        # Describe the workflow execution
        describe_request = DescribeWorkflowExecutionRequest(
            domain=DOMAIN_NAME,
            workflow_execution=WorkflowExecution(
                workflow_id=execution.workflow_id,
                run_id=execution.run_id,
            ),
        )

        response = await client.workflow_stub.DescribeWorkflowExecution(
            describe_request
        )

        # Assert workflow execution info matches
        assert response is not None, "DescribeWorkflowExecution returned None"
        assert response.workflow_execution_info is not None, (
            "workflow_execution_info is None"
        )

        # Verify workflow execution identifiers
        wf_exec = response.workflow_execution_info.workflow_execution
        assert wf_exec.workflow_id == workflow_id, (
            f"workflow_id mismatch: expected {workflow_id}, got {wf_exec.workflow_id}"
        )
        assert wf_exec.run_id == execution.run_id, (
            f"run_id mismatch: expected {execution.run_id}, got {wf_exec.run_id}"
        )

        # Verify workflow type
        assert response.workflow_execution_info.type.name == workflow_type, (
            f"workflow_type mismatch: expected {workflow_type}, got {response.workflow_execution_info.type.name}"
        )

        # Verify task list
        assert response.workflow_execution_info.task_list == task_list_name, (
            f"task_list mismatch: expected {task_list_name}, got {response.workflow_execution_info.task_list}"
        )

        # Verify execution configuration
        assert response.execution_configuration is not None, (
            "execution_configuration is None"
        )

        # Verify task list in configuration
        assert response.execution_configuration.task_list.name == task_list_name, (
            f"config task_list mismatch: expected {task_list_name}, got {response.execution_configuration.task_list.name}"
        )

        # Verify timeouts
        exec_timeout_seconds = response.execution_configuration.execution_start_to_close_timeout.ToSeconds()
        assert exec_timeout_seconds == execution_timeout.total_seconds(), (
            f"execution_start_to_close_timeout mismatch: expected {execution_timeout.total_seconds()}s, got {exec_timeout_seconds}s"
        )

        task_timeout_seconds = (
            response.execution_configuration.task_start_to_close_timeout.ToSeconds()
        )
        assert task_timeout_seconds == task_timeout.total_seconds(), (
            f"task_start_to_close_timeout mismatch: expected {task_timeout.total_seconds()}s, got {task_timeout_seconds}s"
        )


@pytest.mark.usefixtures("helper")
async def test_signal_workflow(helper: CadenceHelper):
    """Test signal_workflow method.

    This integration test verifies:
    1. Starting a workflow execution
    2. Sending a signal to the running workflow
    3. Signal appears in the workflow's history
    """
    async with helper.client() as client:
        workflow_type = "test-workflow-signal"
        task_list_name = "test-task-list-signal"
        workflow_id = "test-workflow-signal-789"
        execution_timeout = timedelta(minutes=5)
        signal_name = "test-signal"
        signal_arg = {"action": "update", "value": 42}

        execution = await client.start_workflow(
            workflow_type,
            task_list=task_list_name,
            execution_start_to_close_timeout=execution_timeout,
            workflow_id=workflow_id,
        )

        await client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            signal_name,
            signal_arg,
        )

        # Fetch workflow history to verify signal was recorded
        history_response = await client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                skip_archival=True,
            )
        )

        # Verify signal event appears in history
        signal_events = [
            event
            for event in history_response.history.events
            if event.HasField("workflow_execution_signaled_event_attributes")
        ]

        assert len(signal_events) == 1, "Expected exactly one signal event in history"
        signal_event = signal_events[0]
        assert (
            signal_event.workflow_execution_signaled_event_attributes.signal_name
            == signal_name
        ), f"Expected signal name '{signal_name}'"


@pytest.mark.usefixtures("helper")
async def test_workflow_id_reuse_policy_reject_duplicate(helper: CadenceHelper):
    """REJECT_DUPLICATE propagates to server and blocks a second start with the same workflow_id.

    This verifies end-to-end that:
    1. The workflow_id_reuse_policy option reaches the Cadence server.
    2. REJECT_DUPLICATE actually causes the server to reject a duplicate start.
    """
    async with helper.client() as client:
        workflow_type = "test-workflow-reuse-reject"
        task_list_name = "test-task-list-reuse-reject"
        workflow_id = "test-workflow-reuse-reject-id"
        execution_timeout = timedelta(minutes=5)

        first_execution = await client.start_workflow(
            workflow_type,
            task_list=task_list_name,
            execution_start_to_close_timeout=execution_timeout,
            workflow_id=workflow_id,
        )

        # Terminate the first run so the second start fails on reuse-policy
        # rather than on "workflow already running".
        await client.workflow_stub.TerminateWorkflowExecution(
            TerminateWorkflowExecutionRequest(
                domain=DOMAIN_NAME,
                workflow_execution=WorkflowExecution(
                    workflow_id=first_execution.workflow_id,
                    run_id=first_execution.run_id,
                ),
                reason="test cleanup for reuse-policy test",
                identity=client.identity,
            )
        )

        with pytest.raises(WorkflowExecutionAlreadyStartedError):
            await client.start_workflow(
                workflow_type,
                task_list=task_list_name,
                execution_start_to_close_timeout=execution_timeout,
                workflow_id=workflow_id,
                workflow_id_reuse_policy=workflow_pb2.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE,
            )


@pytest.mark.usefixtures("helper")
async def test_workflow_id_reuse_policy_terminate_if_running(helper: CadenceHelper):
    """TERMINATE_IF_RUNNING propagates and causes the server to terminate the prior run."""
    async with helper.client() as client:
        workflow_type = "test-workflow-reuse-terminate"
        task_list_name = "test-task-list-reuse-terminate"
        workflow_id = "test-workflow-reuse-terminate-id"
        execution_timeout = timedelta(minutes=5)

        first_execution = await client.start_workflow(
            workflow_type,
            task_list=task_list_name,
            execution_start_to_close_timeout=execution_timeout,
            workflow_id=workflow_id,
        )

        second_execution = await client.start_workflow(
            workflow_type,
            task_list=task_list_name,
            execution_start_to_close_timeout=execution_timeout,
            workflow_id=workflow_id,
            workflow_id_reuse_policy=workflow_pb2.WORKFLOW_ID_REUSE_POLICY_TERMINATE_IF_RUNNING,
        )

        assert second_execution.workflow_id == workflow_id
        assert second_execution.run_id != ""
        assert second_execution.run_id != first_execution.run_id


@pytest.mark.usefixtures("helper")
async def test_signal_with_start_workflow(helper: CadenceHelper):
    """Test signal_with_start_workflow method.

    This integration test verifies:
    1. Starting a workflow via signal_with_start_workflow
    2. Sending a signal to the workflow
    3. Signal appears in the workflow's history with correct name and payload
    """
    async with helper.client() as client:
        workflow_type = "test-workflow-signal-with-start"
        task_list_name = "test-task-list-signal-with-start"
        workflow_id = "test-workflow-signal-with-start-123"
        execution_timeout = timedelta(minutes=5)
        signal_name = "test-signal"
        signal_arg = {"data": "test-signal-data"}

        execution = await client.signal_with_start_workflow(
            workflow_type,
            signal_name,
            [signal_arg],
            "arg1",
            "arg2",
            task_list=task_list_name,
            execution_start_to_close_timeout=execution_timeout,
            workflow_id=workflow_id,
        )

        assert execution is not None
        assert execution.workflow_id == workflow_id
        assert execution.run_id is not None
        assert execution.run_id != ""

        # Fetch workflow history to verify signal was recorded
        history_response = await client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                skip_archival=True,
            )
        )

        # Verify signal event appears in history with correct name and payload
        signal_events = [
            event
            for event in history_response.history.events
            if event.HasField("workflow_execution_signaled_event_attributes")
        ]

        assert len(signal_events) == 1, "Expected exactly one signal event in history"
        signal_event = signal_events[0]
        assert (
            signal_event.workflow_execution_signaled_event_attributes.signal_name
            == signal_name
        ), f"Expected signal name '{signal_name}'"

        # Verify signal payload matches what we sent
        signal_payload_data = signal_event.workflow_execution_signaled_event_attributes.input.data.decode()
        assert signal_arg["data"] in signal_payload_data, (
            f"Expected signal payload to contain '{signal_arg['data']}'"
        )
