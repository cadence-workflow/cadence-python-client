#!/usr/bin/env python3
"""
Example demonstrating how to use the generated gRPC code for Cadence services.
This example shows how to create a gRPC client and make calls to Cadence workflow services.
"""

import grpc
from cadence.api.v1 import service_workflow_grpc, service_workflow, common


def create_grpc_channel(server_address: str = "localhost:7833", use_ssl: bool = False) -> grpc.Channel:
    """
    Create a gRPC channel to connect to Cadence server.
    
    Args:
        server_address: The address of the Cadence server (host:port)
        use_ssl: Whether to use SSL/TLS for the connection
    
    Returns:
        grpc.Channel: The gRPC channel
    """
    if use_ssl:
        # For SSL connections, you would typically use credentials
        credentials = grpc.ssl_channel_credentials()
        return grpc.secure_channel(server_address, credentials)
    else:
        # For insecure connections (development)
        return grpc.insecure_channel(server_address)


def create_workflow_client(channel: grpc.Channel) -> service_workflow_grpc.WorkflowAPIStub:
    """
    Create a gRPC client for the WorkflowAPI service.
    
    Args:
        channel: The gRPC channel
        
    Returns:
        WorkflowAPIStub: The gRPC client stub
    """
    return service_workflow_grpc.WorkflowAPIStub(channel)


def example_start_workflow(client: service_workflow_grpc.WorkflowAPIStub, domain: str, workflow_id: str):
    """
    Example of starting a workflow execution using gRPC.
    
    Args:
        client: The gRPC client
        domain: The Cadence domain
        workflow_id: The workflow ID
    """
    # Create the request message
    request = service_workflow.StartWorkflowExecutionRequest()
    request.domain = domain
    request.workflow_id = workflow_id
    request.workflow_type.name = "MyWorkflow"
    request.task_list.name = "my-task-list"
    request.input.data = b"workflow input data"  # Serialized workflow input
    request.execution_start_to_close_timeout.seconds = 3600  # 1 hour
    request.task_start_to_close_timeout.seconds = 60  # 1 minute
    request.identity = "python-client"
    
    try:
        # Make the gRPC call
        response = client.StartWorkflowExecution(request)
        print(f"✓ Workflow started successfully: {response}")
        return response
    except grpc.RpcError as e:
        print(f"✗ Failed to start workflow: {e}")
        return None


def example_describe_workflow(client: service_workflow_grpc.WorkflowAPIStub, domain: str, workflow_id: str,
 run_id: str):
    """
    Example of describing a workflow execution using gRPC.
    
    Args:
        client: The gRPC client
        domain: The Cadence domain
        workflow_id: The workflow ID
        run_id: The workflow run ID
    """
    # Create the request message
    request = service_workflow.DescribeWorkflowExecutionRequest()
    request.domain = domain
    execution = common.WorkflowExecution()
    execution.workflow_id = workflow_id
    execution.run_id = run_id
    request.workflow_execution.CopyFrom(execution)
    
    try:
        # Make the gRPC call
        response = client.DescribeWorkflowExecution(request)
        print(f"✓ Workflow description: {response}")
        return response
    except grpc.RpcError as e:
        print(f"✗ Failed to describe workflow: {e}")
        return None


def example_get_workflow_history(client: service_workflow_grpc.WorkflowAPIStub, domain: str, workflow_id: str, run_id: str):
    """
    Example of getting workflow execution history using gRPC.
    
    Args:
        client: The gRPC client
        domain: The Cadence domain
        workflow_id: The workflow ID
        run_id: The workflow run ID
    """
    # Create the request message
    request = service_workflow.GetWorkflowExecutionHistoryRequest()
    request.domain = domain
    execution = common.WorkflowExecution()
    execution.workflow_id = workflow_id
    execution.run_id = run_id
    request.workflow_execution.CopyFrom(execution)
    request.page_size = 100
    
    try:
        # Make the gRPC call
        response = client.GetWorkflowExecutionHistory(request)
        print(f"✓ Workflow history retrieved: {len(response.history.events)} events")
        return response
    except grpc.RpcError as e:
        print(f"✗ Failed to get workflow history: {e}")
        return None


def example_query_workflow(client: service_workflow_grpc.WorkflowAPIStub, domain: str, workflow_id: str, run_id: str, query_type: str):
    """
    Example of querying a workflow using gRPC.
    
    Args:
        client: The gRPC client
        domain: The Cadence domain
        workflow_id: The workflow ID
        run_id: The workflow run ID
        query_type: The type of query to execute
    """
    # Create the request message
    request = service_workflow.QueryWorkflowRequest()
    request.domain = domain
    execution = common.WorkflowExecution()
    execution.workflow_id = workflow_id
    execution.run_id = run_id
    request.workflow_execution.CopyFrom(execution)
    request.query.query_type = query_type
    request.query.query_args.data = b"query arguments"  # Serialized query arguments
    
    try:
        # Make the gRPC call
        response = client.QueryWorkflow(request)
        print(f"✓ Workflow query result: {response}")
        return response
    except grpc.RpcError as e:
        print(f"✗ Failed to query workflow: {e}")
        return None


def main():
    """Main example function."""
    print("Cadence gRPC Client Example")
    print("=" * 40)
    
    # Configuration
    server_address = "localhost:7833"  # Default Cadence gRPC port
    domain = "test-domain"
    workflow_id = "example-workflow-123"
    run_id = "example-run-456"
    
    try:
        # Create gRPC channel
        print(f"Connecting to Cadence server at {server_address}...")
        channel = create_grpc_channel(server_address)
        
        # Create gRPC client
        client = create_workflow_client(channel)
        print("✓ gRPC client created successfully")
        
        # Example 1: Start a workflow
        print("\n1. Starting a workflow...")
        example_start_workflow(client, domain, workflow_id)
        
        # Example 2: Describe a workflow
        print("\n2. Describing a workflow...")
        example_describe_workflow(client, domain, workflow_id, run_id)
        
        # Example 3: Get workflow history
        print("\n3. Getting workflow history...")
        example_get_workflow_history(client, domain, workflow_id, run_id)
        
        # Example 4: Query a workflow
        print("\n4. Querying a workflow...")
        example_query_workflow(client, domain, workflow_id, run_id, "status")
        
    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        # Close the channel
        if 'channel' in locals():
            channel.close()
            print("\n✓ gRPC channel closed")


if __name__ == "__main__":
    main() 