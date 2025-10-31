import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Any

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.decisions_helper import DecisionsHelper
from cadence._internal.workflow.decision_events_iterator import DecisionEventsIterator
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence.api.v1.decision_pb2 import Decision
from cadence.client import Client
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.workflow import WorkflowInfo

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    decisions: list[Decision]


class WorkflowEngine:
    def __init__(self, info: WorkflowInfo, client: Client, workflow_definition=None):
        self._workflow_definition = workflow_definition
        self._workflow_instance = None
        if workflow_definition:
            self._workflow_instance = workflow_definition.cls()
        self._decision_manager = DecisionManager()
        self._decisions_helper = DecisionsHelper()
        self._context = Context(
            client, info, self._decisions_helper, self._decision_manager
        )
        self._is_workflow_complete = False

    async def process_decision(
        self, decision_task: PollForDecisionTaskResponse
    ) -> DecisionResult:
        """
        Process a decision task and generate decisions using DecisionEventsIterator.

        This method follows the Java client pattern of using DecisionEventsIterator
        to drive the decision processing pipeline with proper replay handling.

        Args:
            decision_task: The PollForDecisionTaskResponse from the service

        Returns:
            DecisionResult containing the list of decisions
        """
        try:
            # Log decision task processing start with full context (matches Java ReplayDecisionTaskHandler)
            logger.info(
                "Processing decision task for workflow",
                extra={
                    "workflow_type": self._context.info().workflow_type,
                    "workflow_id": self._context.info().workflow_id,
                    "run_id": self._context.info().workflow_run_id,
                    "started_event_id": decision_task.started_event_id,
                    "attempt": decision_task.attempt,
                },
            )

            # Activate workflow context for the entire decision processing
            with self._context._activate():
                # Create DecisionEventsIterator for structured event processing
                events_iterator = DecisionEventsIterator(
                    decision_task, self._context.client()
                )

                # Process decision events using iterator-driven approach
                await self._process_decision_events(events_iterator, decision_task)

                # Collect all pending decisions from state machines
                decisions = self._decision_manager.collect_pending_decisions()

                # Close decider's event loop
                self._close_event_loop()

                # Log decision task completion with metrics (matches Java ReplayDecisionTaskHandler)
                logger.debug(
                    "Decision task completed",
                    extra={
                        "workflow_type": self._context.info().workflow_type,
                        "workflow_id": self._context.info().workflow_id,
                        "run_id": self._context.info().workflow_run_id,
                        "started_event_id": decision_task.started_event_id,
                        "decisions_count": len(decisions),
                        "replay_mode": self._context.is_replay_mode(),
                    },
                )

                return DecisionResult(decisions=decisions)

        except Exception as e:
            # Log decision task failure with full context (matches Java ReplayDecisionTaskHandler)
            logger.error(
                "Decision task processing failed",
                extra={
                    "workflow_type": self._context.info().workflow_type,
                    "workflow_id": self._context.info().workflow_id,
                    "run_id": self._context.info().workflow_run_id,
                    "started_event_id": decision_task.started_event_id,
                    "attempt": decision_task.attempt,
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            # Re-raise the exception so the handler can properly handle the failure
            raise

    async def _process_decision_events(
        self,
        events_iterator: DecisionEventsIterator,
        decision_task: PollForDecisionTaskResponse,
    ) -> None:
        """
        Process decision events using the iterator-driven approach similar to Java client.

        This method implements the three-phase event processing pattern:
        1. Process markers first (for deterministic replay)
        2. Process regular events (trigger workflow state changes)
        3. Execute workflow logic
        4. Process decision events from previous decisions

        Args:
            events_iterator: The DecisionEventsIterator for structured event processing
            decision_task: The original decision task
        """
        # Track if we processed any decision events
        processed_any_decision_events = False

        # Check if there are any decision events to process
        while await events_iterator.has_next_decision_events():
            decision_events = await events_iterator.next_decision_events()
            processed_any_decision_events = True

            # Log decision events batch processing (matches Go client patterns)
            logger.debug(
                "Processing decision events batch",
                extra={
                    "workflow_id": self._context.info().workflow_id,
                    "events_count": len(decision_events.get_events()),
                    "markers_count": len(decision_events.get_markers()),
                    "replay_mode": decision_events.is_replay(),
                    "replay_time": decision_events.replay_current_time_milliseconds,
                },
            )

            # Update context with replay information
            self._context.set_replay_mode(decision_events.is_replay())
            if decision_events.replay_current_time_milliseconds:
                self._context.set_replay_current_time_milliseconds(
                    decision_events.replay_current_time_milliseconds
                )

            # Phase 1: Process markers first for deterministic replay
            for marker_event in decision_events.get_markers():
                try:
                    logger.debug(
                        "Processing marker event",
                        extra={
                            "workflow_id": self._context.info().workflow_id,
                            "marker_name": getattr(
                                marker_event, "marker_name", "unknown"
                            ),
                            "event_id": getattr(marker_event, "event_id", None),
                            "replay_mode": self._context.is_replay_mode(),
                        },
                    )
                    # Process through state machines (DecisionsHelper now delegates to DecisionManager)
                    self._decision_manager.handle_history_event(marker_event)
                except Exception as e:
                    # Warning for unexpected markers (matches Java ClockDecisionContext)
                    logger.warning(
                        "Unexpected marker event encountered",
                        extra={
                            "workflow_id": self._context.info().workflow_id,
                            "marker_name": getattr(
                                marker_event, "marker_name", "unknown"
                            ),
                            "event_id": getattr(marker_event, "event_id", None),
                            "error_type": type(e).__name__,
                        },
                        exc_info=True,
                    )

            # Phase 2: Process regular events to update workflow state
            for event in decision_events.get_events():
                try:
                    logger.debug(
                        "Processing history event",
                        extra={
                            "workflow_id": self._context.info().workflow_id,
                            "event_type": getattr(event, "event_type", "unknown"),
                            "event_id": getattr(event, "event_id", None),
                            "replay_mode": self._context.is_replay_mode(),
                        },
                    )
                    # Process through state machines (DecisionsHelper now delegates to DecisionManager)
                    self._decision_manager.handle_history_event(event)
                except Exception as e:
                    logger.warning(
                        "Error processing history event",
                        extra={
                            "workflow_id": self._context.info().workflow_id,
                            "event_type": getattr(event, "event_type", "unknown"),
                            "event_id": getattr(event, "event_id", None),
                            "error_type": type(e).__name__,
                        },
                        exc_info=True,
                    )

            # Phase 3: Execute workflow logic if not in replay mode
            if not decision_events.is_replay() and not self._is_workflow_complete:
                await self._execute_workflow_function(decision_task)

        # If no decision events were processed but we have history, fall back to direct processing
        # This handles edge cases where the iterator doesn't find decision events
        if (
            not processed_any_decision_events
            and decision_task.history
            and hasattr(decision_task.history, "events")
        ):
            logger.debug(
                "No decision events found by iterator, falling back to direct history processing",
                extra={
                    "workflow_id": self._context.info().workflow_id,
                    "history_events_count": len(decision_task.history.events)
                    if decision_task.history
                    else 0,
                },
            )
            self._fallback_process_workflow_history(decision_task.history)
            if not self._is_workflow_complete:
                await self._execute_workflow_function(decision_task)

    def _fallback_process_workflow_history(self, history) -> None:
        """
        Fallback method to process workflow history events directly.

        This is used when DecisionEventsIterator doesn't find decision events,
        maintaining backward compatibility.

        Args:
            history: The workflow history from the decision task
        """
        if not history or not hasattr(history, "events"):
            return

        logger.debug(
            "Processing history events in fallback mode",
            extra={
                "workflow_id": self._context.info().workflow_id,
                "events_count": len(history.events),
            },
        )

        for event in history.events:
            try:
                # Process through state machines (DecisionsHelper now delegates to DecisionManager)
                self._decision_manager.handle_history_event(event)
            except Exception as e:
                logger.warning(
                    "Error processing history event in fallback mode",
                    extra={
                        "workflow_id": self._context.info().workflow_id,
                        "event_type": getattr(event, "event_type", "unknown"),
                        "event_id": getattr(event, "event_id", None),
                        "error_type": type(e).__name__,
                    },
                    exc_info=True,
                )

    async def _execute_workflow_function(
        self, decision_task: PollForDecisionTaskResponse
    ) -> None:
        """
        Execute the workflow function to generate new decisions.

        This blocks until the workflow schedules an activity or completes.

        Args:
            decision_task: The decision task containing workflow context
        """
        try:
            # Execute the workflow function from the workflow instance
            if self._workflow_definition is None or self._workflow_instance is None:
                logger.warning(
                    "No workflow definition or instance available",
                    extra={
                        "workflow_type": self._context.info().workflow_type,
                        "workflow_id": self._context.info().workflow_id,
                        "run_id": self._context.info().workflow_run_id,
                    },
                )
                return

            # Get the workflow run method from the instance
            workflow_func = self._workflow_definition.get_run_method(
                self._workflow_instance
            )

            # Extract workflow input from history
            workflow_input = self._extract_workflow_input(decision_task)

            # Execute workflow function
            result = await self._execute_workflow_function_once(
                workflow_func, workflow_input
            )

            # Check if workflow is complete
            if result is not None:
                self._is_workflow_complete = True
                # Log workflow completion (matches Go client patterns)
                logger.info(
                    "Workflow execution completed",
                    extra={
                        "workflow_type": self._context.info().workflow_type,
                        "workflow_id": self._context.info().workflow_id,
                        "run_id": self._context.info().workflow_run_id,
                        "completion_type": "success",
                    },
                )

        except Exception as e:
            logger.error(
                "Error executing workflow function",
                extra={
                    "workflow_type": self._context.info().workflow_type,
                    "workflow_id": self._context.info().workflow_id,
                    "run_id": self._context.info().workflow_run_id,
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            raise

    def _extract_workflow_input(
        self, decision_task: PollForDecisionTaskResponse
    ) -> Any:
        """
        Extract workflow input from the decision task history.

        Args:
            decision_task: The decision task containing workflow history

        Returns:
            The workflow input data, or None if not found
        """
        if not decision_task.history or not hasattr(decision_task.history, "events"):
            logger.warning("No history events found in decision task")
            return None

        # Look for WorkflowExecutionStarted event
        for event in decision_task.history.events:
            if hasattr(event, "workflow_execution_started_event_attributes"):
                started_attrs = event.workflow_execution_started_event_attributes
                if started_attrs and hasattr(started_attrs, "input"):
                    # Deserialize the input using the client's data converter
                    try:
                        # Use from_data method with a single type hint of None (no type conversion)
                        input_data_list = (
                            self._context.client().data_converter.from_data(
                                started_attrs.input, [None]
                            )
                        )
                        input_data = input_data_list[0] if input_data_list else None
                        logger.debug(f"Extracted workflow input: {input_data}")
                        return input_data
                    except Exception as e:
                        logger.warning(f"Failed to deserialize workflow input: {e}")
                        return None

        logger.warning("No WorkflowExecutionStarted event found in history")
        return None

    async def _execute_workflow_function_once(
        self, workflow_func: Callable, workflow_input: Any
    ) -> Any:
        """
        Execute the workflow function once (not during replay).

        Args:
            workflow_func: The workflow function to execute
            workflow_input: The input data for the workflow function

        Returns:
            The result of the workflow function execution
        """
        logger.debug(f"Executing workflow function with input: {workflow_input}")
        result = workflow_func(workflow_input)

        # If the workflow function is async, await it properly
        if asyncio.iscoroutine(result):
            result = await result

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
