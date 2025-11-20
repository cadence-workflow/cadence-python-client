import logging
from dataclasses import dataclass

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.decision_events_iterator import DecisionEventsIterator
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence._internal.workflow.workflow_intance import WorkflowInstance
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.decision_pb2 import (
    CompleteWorkflowExecutionDecisionAttributes,
    Decision,
)
from cadence.api.v1.history_pb2 import WorkflowExecutionStartedEventAttributes
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.workflow import WorkflowDefinition, WorkflowInfo

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    decisions: list[Decision]


class WorkflowEngine:
    def __init__(self, info: WorkflowInfo, workflow_definition: WorkflowDefinition):
        self._workflow_instance = WorkflowInstance(
            workflow_definition, info.data_converter
        )
        self._decision_manager = (
            DecisionManager()
        )  # TODO: remove this stateful object and use the context instead
        self._context = Context(info, self._decision_manager)

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
            # Activate workflow context for the entire decision processing
            with self._context._activate() as ctx:
                # Log decision task processing start with full context (matches Java ReplayDecisionTaskHandler)
                logger.info(
                    "Processing decision task for workflow",
                    extra={
                        "workflow_type": ctx.info().workflow_type,
                        "workflow_id": ctx.info().workflow_id,
                        "run_id": ctx.info().workflow_run_id,
                        "started_event_id": decision_task.started_event_id,
                        "attempt": decision_task.attempt,
                    },
                )

                # Create DecisionEventsIterator for structured event processing
                events_iterator = DecisionEventsIterator(
                    decision_task, ctx.info().workflow_events
                )

                # Process decision events using iterator-driven approach
                self._process_decision_events(ctx, events_iterator, decision_task)

                # Collect all pending decisions from state machines
                decisions = self._decision_manager.collect_pending_decisions()

                # complete workflow if it is done
                try:
                    if self._workflow_instance.is_done():
                        result = self._workflow_instance.get_result()
                        decisions.append(
                            Decision(
                                complete_workflow_execution_decision_attributes=CompleteWorkflowExecutionDecisionAttributes(
                                    result=result
                                )
                            )
                        )
                    return DecisionResult(decisions=decisions)

                except Exception:
                    # TODO: handle CancellationError
                    # TODO: handle WorkflowError
                    # TODO: handle unknown error, fail decision task and try again instead of breaking the engine
                    raise

        except Exception as e:
            # Log decision task failure with full context (matches Java ReplayDecisionTaskHandler)
            logger.error(
                "Decision task processing failed",
                extra={
                    "workflow_type": ctx.info().workflow_type,
                    "workflow_id": ctx.info().workflow_id,
                    "run_id": ctx.info().workflow_run_id,
                    "started_event_id": decision_task.started_event_id,
                    "attempt": decision_task.attempt,
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            # Re-raise the exception so the handler can properly handle the failure
            raise

    def is_done(self) -> bool:
        return self._workflow_instance.is_done()

    def _process_decision_events(
        self,
        ctx: Context,
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
                    "workflow_id": ctx.info().workflow_id,
                    "events_count": len(decision_events.get_events()),
                    "markers_count": len(decision_events.get_markers()),
                    "replay_mode": decision_events.is_replay(),
                    "replay_time": decision_events.replay_current_time_milliseconds,
                },
            )

            # Update context with replay information
            ctx.set_replay_mode(decision_events.is_replay())
            if decision_events.replay_current_time_milliseconds:
                ctx.set_replay_current_time_milliseconds(
                    decision_events.replay_current_time_milliseconds
                )

            # Phase 1: Process markers first
            for marker_event in decision_events.markers:
                logger.debug(
                    "Processing marker event",
                    extra={
                        "workflow_id": ctx.info().workflow_id,
                        "marker_name": getattr(marker_event, "marker_name", "unknown"),
                        "event_id": getattr(marker_event, "event_id", None),
                        "replay_mode": ctx.is_replay_mode(),
                    },
                )
                # Process through state machines (DecisionsHelper now delegates to DecisionManager)
                self._decision_manager.handle_history_event(marker_event)

            # Phase 2: Process regular input events
            for event in decision_events.input:
                logger.debug(
                    "Processing history event",
                    extra={
                        "workflow_id": ctx.info().workflow_id,
                        "event_type": getattr(event, "event_type", "unknown"),
                        "event_id": getattr(event, "event_id", None),
                        "replay_mode": ctx.is_replay_mode(),
                    },
                )
                # Process through state machines (DecisionsHelper now delegates to DecisionManager)
                self._decision_manager.handle_history_event(event)

            # Phase 3: Execute workflow logic
            if not self._workflow_instance.is_started():
                self._workflow_instance.start(
                    self._extract_workflow_input(decision_task)
                )

            self._workflow_instance.run_once()

            # Phase 4: update state machine with output events
            for event in decision_events.output:
                self._decision_manager.handle_history_event(event)

    def _extract_workflow_input(
        self, decision_task: PollForDecisionTaskResponse
    ) -> Payload:
        """
        Extract workflow input from the decision task history.

        Args:
            decision_task: The decision task containing workflow history

        Returns:
            The workflow input data, or None if not found
        """
        if not decision_task.history or not hasattr(decision_task.history, "events"):
            raise ValueError("No history events found in decision task")

        # Look for WorkflowExecutionStarted event
        for event in decision_task.history.events:
            if hasattr(event, "workflow_execution_started_event_attributes"):
                started_attrs: WorkflowExecutionStartedEventAttributes = (
                    event.workflow_execution_started_event_attributes
                )
                if started_attrs and hasattr(started_attrs, "input"):
                    return started_attrs.input

        raise ValueError("No WorkflowExecutionStarted event found in history")
