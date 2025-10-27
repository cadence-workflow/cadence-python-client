from datetime import timedelta
import pytest
from cadence.api.v1.service_domain_pb2 import DescribeDomainRequest, DescribeDomainResponse
from cadence.api.v1.service_workflow_pb2 import DescribeWorkflowExecutionRequest
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.error import EntityNotExistsError
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

@pytest.mark.usefixtures("helper")
async def test_domain_exists(helper: CadenceHelper):
    async with helper.client() as client:
        response: DescribeDomainResponse = await client.domain_stub.DescribeDomain(DescribeDomainRequest(name=DOMAIN_NAME))
        assert response.domain.name == DOMAIN_NAME

@pytest.mark.usefixtures("helper")
async def test_domain_not_exists(helper: CadenceHelper):
    with pytest.raises(EntityNotExistsError):
        async with helper.client() as client:
            await client.domain_stub.DescribeDomain(DescribeDomainRequest(name="unknown-domain"))

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
        
        response = await client.workflow_stub.DescribeWorkflowExecution(describe_request)
        
        # Assert workflow execution info matches
        assert response is not None, "DescribeWorkflowExecution returned None"
        assert response.workflow_execution_info is not None, "workflow_execution_info is None"
        
        # Verify workflow execution identifiers
        wf_exec = response.workflow_execution_info.workflow_execution
        assert wf_exec.workflow_id == workflow_id, \
            f"workflow_id mismatch: expected {workflow_id}, got {wf_exec.workflow_id}"
        assert wf_exec.run_id == execution.run_id, \
            f"run_id mismatch: expected {execution.run_id}, got {wf_exec.run_id}"
        
        # Verify workflow type
        assert response.workflow_execution_info.type.name == workflow_type, \
            f"workflow_type mismatch: expected {workflow_type}, got {response.workflow_execution_info.type.name}"
        
        # Verify task list
        assert response.workflow_execution_info.task_list == task_list_name, \
            f"task_list mismatch: expected {task_list_name}, got {response.workflow_execution_info.task_list}"
        
        # Verify execution configuration
        assert response.execution_configuration is not None, "execution_configuration is None"
        
        # Verify task list in configuration
        assert response.execution_configuration.task_list.name == task_list_name, \
            f"config task_list mismatch: expected {task_list_name}, got {response.execution_configuration.task_list.name}"
        
        # Verify timeouts
        exec_timeout_seconds = response.execution_configuration.execution_start_to_close_timeout.ToSeconds()
        assert exec_timeout_seconds == execution_timeout.total_seconds(), \
            f"execution_start_to_close_timeout mismatch: expected {execution_timeout.total_seconds()}s, got {exec_timeout_seconds}s"
        
        task_timeout_seconds = response.execution_configuration.task_start_to_close_timeout.ToSeconds()
        assert task_timeout_seconds == task_timeout.total_seconds(), \
            f"task_start_to_close_timeout mismatch: expected {task_timeout.total_seconds()}s, got {task_timeout_seconds}s"
