import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.decisions_helper import DecisionsHelper
from cadence._internal.workflow.decision_events_iterator import DecisionEventsIterator
from cadence._internal.workflow.deterministic_event_loop import DeterministicEventLoop
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence._internal.workflow.workflow_intance import WorkflowInstance
from cadence.api.v1.decision_pb2 import Decision
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.workflow import WorkflowDefinition, WorkflowInfo

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    decisions: list[Decision]


class WorkflowEngine:
    def __init__(self, info: WorkflowInfo, workflow_definition: WorkflowDefinition):
        self._workflow_instance = WorkflowInstance(workflow_definition)
        self._decision_manager = DecisionManager()
        self._decisions_helper = DecisionsHelper()
        self._context = Context(info, self._decisions_helper, self._decision_manager)
        self._loop = DeterministicEventLoop()
        self._task: Optional[asyncio.Task] = None

    def process_decision(
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
                    decision_task, self._context.info().workflow_events
                )

                # Process decision events using iterator-driven approach
                self._process_decision_events(events_iterator, decision_task)

                # Collect all pending decisions from state machines
                decisions = self._decision_manager.collect_pending_decisions()

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

    def is_done(self) -> bool:
        return self._task is not None and self._task.done()

    def _process_decision_events(
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

        # Check if there are any decision events to process
        for decision_events in events_iterator:
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

            # Phase 3: Execute workflow logic
            self._execute_workflow_once(decision_task)

    def _execute_workflow_once(
        self, decision_task: PollForDecisionTaskResponse
    ) -> None:
        """
        Execute the workflow function to generate new decisions.

        This blocks until the workflow schedules an activity or completes.

        Args:
            decision_task: The decision task containing workflow context
        """
        try:
            # Extract workflow input from history
            if self._task is None:
                workflow_input = self._extract_workflow_input(decision_task)
                self._task = self._loop.create_task(
                    self._workflow_instance.run(workflow_input)
                )

                self._loop.run_until_yield()

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
                        input_data_list = self._context.data_converter().from_data(
                            started_attrs.input, [None]
                        )
                        input_data = input_data_list[0] if input_data_list else None
                        logger.debug(f"Extracted workflow input: {input_data}")
                        return input_data
                    except Exception as e:
                        logger.warning(f"Failed to deserialize workflow input: {e}")
                        return None

        logger.warning("No WorkflowExecutionStarted event found in history")
        return None
