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
async def test_workflow_stub_accessible(helper: CadenceHelper):
    """Test that workflow_stub is properly initialized and accessible."""
    async with helper.client() as client:
        assert client.workflow_stub is not None
        # Verify it's the correct type
        from cadence.api.v1.service_workflow_pb2_grpc import WorkflowAPIStub
        assert isinstance(client.workflow_stub, WorkflowAPIStub)

@pytest.mark.usefixtures("helper")
async def test_workflow_stub_start_workflow(helper: CadenceHelper):
    """Test starting a workflow execution via workflow_stub.
    
    This test verifies that we can start a workflow execution using the
    client's start_workflow method, which uses workflow_stub internally.
    """
    async with helper.client() as client:
        # Start a simple workflow
        execution = await client.start_workflow(
            "test-workflow-type",
            task_list="test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=5),
            workflow_id="test-workflow-id-123",
        )
        
        # Verify we got a valid execution response
        assert execution is not None
        assert execution.workflow_id == "test-workflow-id-123"
        assert execution.run_id is not None
        assert len(execution.run_id) > 0

@pytest.mark.usefixtures("helper")
async def test_workflow_stub_describe_workflow(helper: CadenceHelper):
    """Test describing a workflow execution via workflow_stub.
    
    This test verifies that we can query workflow execution details after
    starting a workflow.
    """
    async with helper.client() as client:
        # First start a workflow
        execution = await client.start_workflow(
            "test-workflow-type-describe",
            task_list="test-task-list-describe",
            execution_start_to_close_timeout=timedelta(minutes=5),
            workflow_id="test-workflow-describe-456",
        )
        
        # Now describe the workflow execution
        describe_request = DescribeWorkflowExecutionRequest(
            domain=DOMAIN_NAME,
            workflow_execution=WorkflowExecution(
                workflow_id=execution.workflow_id,
                run_id=execution.run_id,
            ),
        )
        
        response = await client.workflow_stub.DescribeWorkflowExecution(describe_request)
        
        # Print the run_id for debugging
        print(f"Workflow run_id: {execution.run_id}")
        
        # Verify we got a valid response
        assert response is not None
        assert response.workflow_execution_info is not None
        assert response.workflow_execution_info.workflow_execution.workflow_id == execution.workflow_id
        assert response.workflow_execution_info.workflow_execution.run_id == execution.run_id

# Combined Test

@pytest.mark.usefixtures("helper")
async def test_all_stubs_accessible(helper: CadenceHelper):
    """Test that all three stubs (domain, worker, workflow) are accessible.
    
    This is a comprehensive connectivity test that verifies the client
    can access all three main API stubs.
    """
    async with helper.client() as client:
        # Verify all stubs are initialized
        assert client.domain_stub is not None
        assert client.worker_stub is not None
        assert client.workflow_stub is not None
        
        # Verify they are the correct types
        from cadence.api.v1.service_domain_pb2_grpc import DomainAPIStub
        from cadence.api.v1.service_worker_pb2_grpc import WorkerAPIStub
        from cadence.api.v1.service_workflow_pb2_grpc import WorkflowAPIStub
        
        assert isinstance(client.domain_stub, DomainAPIStub)
        assert isinstance(client.worker_stub, WorkerAPIStub)
        assert isinstance(client.workflow_stub, WorkflowAPIStub)
        
        # Test basic connectivity with each stub
        # Domain stub - describe domain
        domain_response = await client.domain_stub.DescribeDomain(
            DescribeDomainRequest(name=DOMAIN_NAME)
        )
        assert domain_response.domain.name == DOMAIN_NAME
        
        # Workflow stub - start workflow
        execution = await client.start_workflow(
            "connectivity-test-workflow",
            task_list="connectivity-test-task-list",
            execution_start_to_close_timeout=timedelta(minutes=5),
            workflow_id="connectivity-test-workflow-789",
        )
        assert execution.workflow_id == "connectivity-test-workflow-789"
