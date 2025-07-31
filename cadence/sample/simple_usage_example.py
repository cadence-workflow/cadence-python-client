#!/usr/bin/env python3
"""
Simple usage example for cadence protobuf modules.
This demonstrates basic usage patterns for the generated protobuf classes.
"""

import sys
import os

# Add the project root to the path so we can import cadence modules
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)


def example_workflow_execution():
    """Example of creating and using WorkflowExecution objects."""
    print("=== Workflow Execution Example ===")
    
    from cadence.api.v1 import common, workflow
    
    # Create a workflow execution
    wf_exec = common.WorkflowExecution()
    wf_exec.workflow_id = "my-workflow-123"
    wf_exec.run_id = "run-456"
    
    print(f"Created workflow execution:")
    print(f"  - Workflow ID: {wf_exec.workflow_id}")
    print(f"  - Run ID: {wf_exec.run_id}")
    
    # Create workflow execution info
    wf_info = workflow.WorkflowExecutionInfo()
    wf_info.workflow_execution.CopyFrom(wf_exec)
    wf_info.type.name = "MyWorkflowType"
    wf_info.start_time.seconds = 1234567890
    wf_info.close_time.seconds = 1234567990
    
    print(f"Created workflow execution info:")
    print(f"  - Type: {wf_info.type.name}")
    print(f"  - Start Time: {wf_info.start_time.seconds}")
    print(f"  - Close Time: {wf_info.close_time.seconds}")
    
    return wf_exec, wf_info


def example_domain_operations():
    """Example of creating and using Domain objects."""
    print("\n=== Domain Operations Example ===")
    
    from cadence.api.v1 import domain
    
    # Create a domain
    domain_obj = domain.Domain()
    domain_obj.name = "my-domain"
    domain_obj.status = domain.DOMAIN_STATUS_REGISTERED
    domain_obj.description = "My test domain"
    
    print(f"Created domain:")
    print(f"  - Name: {domain_obj.name}")
    print(f"  - Status: {domain_obj.status}")
    print(f"  - Description: {domain_obj.description}")
    
    return domain_obj


def example_enum_usage():
    """Example of using enum values."""
    print("\n=== Enum Usage Example ===")
    
    from cadence.api.v1 import workflow
    
    # Workflow execution close status
    print("Workflow Execution Close Status:")
    print(f"  - COMPLETED: {workflow.WORKFLOW_EXECUTION_CLOSE_STATUS_COMPLETED}")
    print(f"  - FAILED: {workflow.WORKFLOW_EXECUTION_CLOSE_STATUS_FAILED}")
    print(f"  - CANCELED: {workflow.WORKFLOW_EXECUTION_CLOSE_STATUS_CANCELED}")
    print(f"  - TERMINATED: {workflow.WORKFLOW_EXECUTION_CLOSE_STATUS_TERMINATED}")
    print(f"  - TIMED_OUT: {workflow.WORKFLOW_EXECUTION_CLOSE_STATUS_TIMED_OUT}")
    
    # Timeout types
    print("\nTimeout Types:")
    print(f"  - START_TO_CLOSE: {workflow.TIMEOUT_TYPE_START_TO_CLOSE}")
    print(f"  - SCHEDULE_TO_CLOSE: {workflow.TIMEOUT_TYPE_SCHEDULE_TO_CLOSE}")
    print(f"  - SCHEDULE_TO_START: {workflow.TIMEOUT_TYPE_SCHEDULE_TO_START}")
    print(f"  - HEARTBEAT: {workflow.TIMEOUT_TYPE_HEARTBEAT}")
    
    # Parent close policies
    print("\nParent Close Policies:")
    print(f"  - TERMINATE: {workflow.PARENT_CLOSE_POLICY_TERMINATE}")
    print(f"  - ABANDON: {workflow.PARENT_CLOSE_POLICY_ABANDON}")
    print(f"  - REQUEST_CANCEL: {workflow.PARENT_CLOSE_POLICY_REQUEST_CANCEL}")


def example_serialization():
    """Example of serializing and deserializing protobuf objects."""
    print("\n=== Serialization Example ===")
    
    from cadence.api.v1 import common, workflow
    
    # Create a workflow execution
    wf_exec = common.WorkflowExecution()
    wf_exec.workflow_id = "serialization-test"
    wf_exec.run_id = "run-789"
    
    # Serialize to bytes
    serialized = wf_exec.SerializeToString()
    print(f"Serialized size: {len(serialized)} bytes")
    
    # Deserialize from bytes
    new_wf_exec = common.WorkflowExecution()
    new_wf_exec.ParseFromString(serialized)
    
    print(f"Deserialized workflow execution:")
    print(f"  - Workflow ID: {new_wf_exec.workflow_id}")
    print(f"  - Run ID: {new_wf_exec.run_id}")
    
    # Verify they're equal
    if wf_exec.workflow_id == new_wf_exec.workflow_id and wf_exec.run_id == new_wf_exec.run_id:
        print("✓ Serialization/deserialization successful!")
    else:
        print("✗ Serialization/deserialization failed!")


def main():
    """Main example function."""
    print("🚀 Cadence Protobuf Usage Examples")
    print("=" * 50)
    
    try:
        # Run all examples
        example_workflow_execution()
        example_domain_operations()
        example_enum_usage()
        example_serialization()
        
        print("\n" + "=" * 50)
        print("✅ All examples completed successfully!")
        print("The protobuf modules are working correctly and ready for use.")
        
    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main()) 