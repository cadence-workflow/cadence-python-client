import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any

from cadence._internal.workflow.context import Context
from cadence.api.v1.decision_pb2 import Decision
from cadence.client import Client
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.workflow import WorkflowInfo
from cadence._internal.decision_state_machine import DecisionManager

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    decisions: list[Decision]
    force_create_new_decision_task: bool = False
    query_results: Optional[Dict[str, Any]] = None

class WorkflowEngine:
    def __init__(self, info: WorkflowInfo, client: Client, workflow_func: Callable[[Any], Any] | None = None):
        self._context = Context(client, info)
        self._workflow_func = workflow_func
        self._decision_manager = DecisionManager()
        self._is_workflow_complete = False

    async def process_decision(self, decision_task: PollForDecisionTaskResponse) -> DecisionResult:
        """
        Process a decision task and generate decisions.
        
        Args:
            decision_task: The PollForDecisionTaskResponse from the service
            
        Returns:
            DecisionResult containing the list of decisions
        """
        try:
            logger.info(f"Processing decision task for workflow {self._context.info().workflow_id}")
            
            # Process workflow history to update decision state machines
            if decision_task.history:
                self._process_workflow_history(decision_task.history)
            
            # Execute workflow function to generate new decisions
            if not self._is_workflow_complete:
                await self._execute_workflow_function(decision_task)
            
            # Collect all pending decisions from state machines
            decisions = self._decision_manager.collect_pending_decisions()
            
            # Close decider's event loop
            self._close_event_loop()
            
            logger.info(f"Generated {len(decisions)} decisions for workflow {self._context.info().workflow_id}")
            
            return DecisionResult(decisions=decisions)
            
        except Exception:
            logger.exception(f"Error processing decision task for workflow {self._context.info().workflow_id}")
            # Return empty decisions on error - the task will be failed by the handler
            return DecisionResult(decisions=[])
    
    def _process_workflow_history(self, history) -> None:
        """
        Process workflow history events to update decision state machines.
        
        Args:
            history: The workflow history from the decision task
        """
        if not history or not hasattr(history, 'events'):
            return
            
        logger.debug(f"Processing {len(history.events)} history events")
        
        for event in history.events:
            try:
                self._decision_manager.handle_history_event(event)
            except Exception as e:
                logger.warning(f"Error processing history event: {e}")
    
    async def _execute_workflow_function(self, decision_task: PollForDecisionTaskResponse) -> None:
        """
        Execute the workflow function to generate new decisions.
        
        This blocks until the workflow schedules an activity or completes.
        
        Args:
            decision_task: The decision task containing workflow context
        """
        try:
            with self._context._activate():
                # Execute the workflow function
                # The workflow function should block until it schedules an activity
                workflow_func = self._workflow_func
                if workflow_func is None:
                    logger.warning(f"No workflow function available for workflow {self._context.info().workflow_id}")
                    return
                
                # Extract workflow input from history
                workflow_input = await self._extract_workflow_input(decision_task)
                
                # Execute workflow function
                result = self._execute_workflow_function_sync(workflow_func, workflow_input)
                
                # Check if workflow is complete
                if result is not None:
                    self._is_workflow_complete = True
                    logger.info(f"Workflow {self._context.info().workflow_id} completed")
                
        except Exception:
            logger.exception(f"Error executing workflow function for {self._context.info().workflow_id}")
            raise
    
    async def _extract_workflow_input(self, decision_task: PollForDecisionTaskResponse) -> Any:
        """
        Extract workflow input from the decision task history.
        
        Args:
            decision_task: The decision task containing workflow history
            
        Returns:
            The workflow input data, or None if not found
        """
        if not decision_task.history or not hasattr(decision_task.history, 'events'):
            logger.warning("No history events found in decision task")
            return None
            
        # Look for WorkflowExecutionStarted event
        for event in decision_task.history.events:
            if hasattr(event, 'workflow_execution_started_event_attributes'):
                started_attrs = event.workflow_execution_started_event_attributes
                if started_attrs and hasattr(started_attrs, 'input'):
                    # Deserialize the input using the client's data converter
                    try:
                        # Use from_data method with a single type hint of None (no type conversion)
                        input_data_list = await self._context.client().data_converter.from_data(started_attrs.input, [None])
                        input_data = input_data_list[0] if input_data_list else None
                        logger.debug(f"Extracted workflow input: {input_data}")
                        return input_data
                    except Exception as e:
                        logger.warning(f"Failed to deserialize workflow input: {e}")
                        return None
        
        logger.warning("No WorkflowExecutionStarted event found in history")
        return None
    
    def _execute_workflow_function_sync(self, workflow_func: Callable, workflow_input: Any) -> Any:
        """
        Execute the workflow function synchronously.
        
        Args:
            workflow_func: The workflow function to execute
            workflow_input: The input data for the workflow function
            
        Returns:
            The result of the workflow function execution
        """
        logger.debug(f"Executing workflow function with input: {workflow_input}")
        result = workflow_func(workflow_input)
        
        # If the workflow function is async, we need to handle it properly
        if asyncio.iscoroutine(result):
            # Create a simple event loop for async workflow functions
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(result)
            finally:
                loop.close()
                asyncio.set_event_loop(None)
        
        return result
    
    def _close_event_loop(self) -> None:
        """
        Close the decider's event loop.
        """
        try:
            # Get the current event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule the loop to stop
                loop.call_soon_threadsafe(loop.stop)
                logger.debug("Scheduled event loop to stop")
        except Exception as e:
            logger.warning(f"Error closing event loop: {e}")
