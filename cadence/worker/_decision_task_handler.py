import logging
from typing import Dict

from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.service_worker_pb2 import (
    PollForDecisionTaskResponse,
    RespondDecisionTaskCompletedRequest,
    RespondDecisionTaskFailedRequest
)
from cadence.api.v1.workflow_pb2 import DecisionTaskFailedCause
from cadence.client import Client
from cadence.worker._base_task_handler import BaseTaskHandler
from cadence._internal.workflow.workflow_engine import WorkflowEngine, DecisionResult
from cadence._internal.workflow.context import Context
from cadence.workflow import WorkflowInfo
from cadence.worker._registry import Registry

logger = logging.getLogger(__name__)

class DecisionTaskHandler(BaseTaskHandler[PollForDecisionTaskResponse]):
    """
    Task handler for processing decision tasks.
    
    This handler processes decision tasks and generates decisions using the workflow engine.
    """
    
    def __init__(self, client: Client, task_list: str, registry: Registry, identity: str = "unknown", **options):
        """
        Initialize the decision task handler.
        
        Args:
            client: The Cadence client instance
            task_list: The task list name
            registry: Registry containing workflow functions
            identity: The worker identity
            **options: Additional options for the handler
        """
        super().__init__(client, task_list, identity, **options)
        self._registry = registry
        self._workflow_engines: Dict[str, WorkflowEngine] = {}
        
    
    async def _handle_task_implementation(self, task: PollForDecisionTaskResponse) -> None:
        """
        Handle a decision task implementation.
        
        Args:
            task: The decision task to handle
        """
        # Extract workflow execution info
        workflow_execution = task.workflow_execution
        workflow_type = task.workflow_type
        
        if not workflow_execution or not workflow_type:
            logger.error("Decision task missing workflow execution or type")
            raise ValueError("Missing workflow execution or type")
        
        workflow_id = workflow_execution.workflow_id
        run_id = workflow_execution.run_id
        workflow_type_name = workflow_type.name
        
        logger.info(f"Processing decision task for workflow {workflow_id} (type: {workflow_type_name})")
        
        # Get or create workflow engine for this workflow execution
        engine_key = f"{workflow_id}:{run_id}"
        if engine_key not in self._workflow_engines:
            # Get the workflow function from registry
            try:
                workflow_func = self._registry.get_workflow(workflow_type_name)
            except KeyError:
                logger.error(f"Workflow type '{workflow_type_name}' not found in registry")
                raise KeyError(f"Workflow type '{workflow_type_name}' not found")
            
            # Create workflow info and engine
            workflow_info = WorkflowInfo(
                workflow_type=workflow_type_name,
                workflow_domain=self._client.domain,
                workflow_id=workflow_id,
                workflow_run_id=run_id
            )
            
            self._workflow_engines[engine_key] = WorkflowEngine(
                info=workflow_info, 
                client=self._client, 
                workflow_func=workflow_func
            )
        
        # Create workflow context and execute with it active
        workflow_engine = self._workflow_engines[engine_key]
        workflow_info = WorkflowInfo(
            workflow_type=workflow_type_name,
            workflow_domain=self._client.domain,
            workflow_id=workflow_id,
            workflow_run_id=run_id
        )
        
        context = Context(client=self._client, info=workflow_info)
        with context._activate():
            # Process the decision using the workflow engine
            decision_result = await workflow_engine.process_decision(task)
            
            # Respond with the decisions
            await self._respond_decision_task_completed(task, decision_result)
        
        logger.info(f"Successfully processed decision task for workflow {workflow_id}")
    
    async def handle_task_failure(self, task: PollForDecisionTaskResponse, error: Exception) -> None:
        """
        Handle decision task processing failure.
        
        Args:
            task: The task that failed
            error: The exception that occurred
        """
        try:
            logger.error(f"Decision task failed: {error}")
            
            # Determine the failure cause
            cause = DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_UNHANDLED_DECISION
            if isinstance(error, KeyError):
                cause = DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_WORKFLOW_WORKER_UNHANDLED_FAILURE
            elif isinstance(error, ValueError):
                cause = DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_BAD_SCHEDULE_ACTIVITY_ATTRIBUTES
            
            # Create error details
            error_message = str(error).encode('utf-8')
            details = Payload(data=error_message)
            
            # Respond with failure
            await self._client.worker_stub.RespondDecisionTaskFailed(
                RespondDecisionTaskFailedRequest(
                    task_token=task.task_token,
                    cause=cause,
                    identity=self._identity,
                    details=details
                )
            )
            
            logger.info("Decision task failure response sent")
            
        except Exception:
            logger.exception("Error handling decision task failure")
    
    async def _respond_decision_task_completed(self, task: PollForDecisionTaskResponse, decision_result: DecisionResult) -> None:
        """
        Respond to the service that the decision task has been completed.
        
        Args:
            task: The original decision task
            decision_result: The result containing decisions and query results
        """
        try:
            request = RespondDecisionTaskCompletedRequest(
                task_token=task.task_token,
                decisions=decision_result.decisions,
                identity=self._identity,
                return_new_decision_task=decision_result.force_create_new_decision_task,
                force_create_new_decision_task=decision_result.force_create_new_decision_task
            )
            
            # Add query results if present
            if decision_result.query_results:
                request.query_results.update(decision_result.query_results)
            
            await self._client.worker_stub.RespondDecisionTaskCompleted(request)
            logger.debug(f"Decision task completed with {len(decision_result.decisions)} decisions")
            
        except Exception:
            logger.exception("Error responding to decision task completion")
            raise
    
    def cleanup_workflow_engine(self, workflow_id: str, run_id: str) -> None:
        """
        Clean up a workflow engine when workflow execution is complete.
        
        Args:
            workflow_id: The workflow ID
            run_id: The run ID
        """
        engine_key = f"{workflow_id}:{run_id}"
        if engine_key in self._workflow_engines:
            del self._workflow_engines[engine_key]
            logger.debug(f"Cleaned up workflow engine for {workflow_id}:{run_id}")
