import logging
import traceback
from asyncio import CancelledError, InvalidStateError
from dataclasses import dataclass
from typing import List, Optional

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.decision_events_iterator import DecisionEventsIterator
from cadence._internal.workflow.deterministic_event_loop import (
    DeterministicEventLoop,
    FatalDecisionError,
)
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence._internal.workflow.workflow_instance import WorkflowInstance
from cadence.api.v1 import history
from cadence.api.v1.common_pb2 import Failure
from cadence.api.v1.decision_pb2 import (
    Decision,
    FailWorkflowExecutionDecisionAttributes,
    CompleteWorkflowExecutionDecisionAttributes,
)
from cadence.api.v1.history_pb2 import (
    HistoryEvent,
    WorkflowExecutionStartedEventAttributes,
)
from cadence.workflow import WorkflowDefinition, WorkflowInfo

logger = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    decisions: list[Decision]


class WorkflowEngine:
    def __init__(self, info: WorkflowInfo, workflow_definition: WorkflowDefinition):
        self._event_loop = DeterministicEventLoop()
        self._decision_manager = DecisionManager(self._event_loop)
        self._workflow_instance = WorkflowInstance(
            self._event_loop,
            workflow_definition,
            info.data_converter,
        )
        self._context = Context(info, self._decision_manager)

    def process_decision(
        self,
        events: List[HistoryEvent],
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
                    },
                )

                # Create DecisionEventsIterator for structured event processing
                events_iterator = DecisionEventsIterator(events)

                # Process decision events using iterator-driven approach
                self._process_decision_events(ctx, events_iterator)

                # Collect all pending decisions from state machines
                decisions = self._decision_manager.collect_pending_decisions()

                return DecisionResult(decisions=decisions)

        except Exception as e:
            # Log decision task failure with full context (matches Java ReplayDecisionTaskHandler)
            logger.error(
                "Decision task processing failed",
                extra={
                    "workflow_type": ctx.info().workflow_type,
                    "workflow_id": ctx.info().workflow_id,
                    "run_id": ctx.info().workflow_run_id,
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
                    "markers_count": len(decision_events.markers),
                    "replay_mode": decision_events.replay,
                    "replay_time": decision_events.replay_current_time_milliseconds,
                },
            )

            # Update context with replay information
            ctx.set_replay_mode(decision_events.replay)
            if decision_events.replay_current_time_milliseconds:
                ctx.set_replay_current_time_milliseconds(
                    decision_events.replay_current_time_milliseconds
                )
            with self._decision_manager.track_nondeterminism(
                decision_events.replay, decision_events.output
            ):
                # Phase 1: Process markers first
                for marker_event in decision_events.markers:
                    logger.debug(
                        "Processing marker event",
                        extra={
                            "workflow_id": ctx.info().workflow_id,
                            "marker_name": getattr(
                                marker_event, "marker_name", "unknown"
                            ),
                            "event_id": getattr(marker_event, "event_id", None),
                            "replay_mode": decision_events.replay,
                        },
                    )
                    # Process through state machines (DecisionsHelper now delegates to DecisionManager)
                    self._decision_manager.handle_history_event(marker_event)

                # Phase 2: Process regular input events
                for event in decision_events.input:
                    self._apply_input_event(event)

                # Phase 3: Execute workflow logic
                self._workflow_instance.run_until_yield()

                # If the workflow function returned (or threw an exception), we're done
                # If it completed early (or late), the nondeterminism tracking will catch that
                if decision := self._maybe_complete_workflow():
                    self._decision_manager.complete_workflow(decision)

            # Phase 4: update state machine with output events
            for event in decision_events.output:
                self._decision_manager.handle_history_event(event)

    def _maybe_complete_workflow(self) -> Optional[Decision]:
        try:
            if result := self._workflow_instance.get_result():
                return Decision(
                    complete_workflow_execution_decision_attributes=CompleteWorkflowExecutionDecisionAttributes(
                        result=result,
                    )
                )
            else:
                return None
        except (CancelledError, InvalidStateError, FatalDecisionError):
            raise
        except ExceptionGroup as e:
            if e.subgroup((InvalidStateError, FatalDecisionError)):
                raise
            failure = _failure_from_exception(e)

            return Decision(
                fail_workflow_execution_decision_attributes=FailWorkflowExecutionDecisionAttributes(
                    failure=failure
                )
            )

        except Exception as e:
            failure = _failure_from_exception(e)
            return Decision(
                fail_workflow_execution_decision_attributes=FailWorkflowExecutionDecisionAttributes(
                    failure=failure
                )
            )

    def _apply_input_event(self, event: history.HistoryEvent) -> None:
        logger.debug(
            "Processing history event",
            extra={
                "workflow_id": self._context.info().workflow_id,
                "event_type": getattr(event, "event_type", "unknown"),
                "event_id": getattr(event, "event_id", None),
                "replay_mode": self._context.is_replay_mode(),
            },
        )
        # start workflow on workflow started event
        if (
            event.WhichOneof("attributes")
            == "workflow_execution_started_event_attributes"
        ):
            started_attrs: WorkflowExecutionStartedEventAttributes = (
                event.workflow_execution_started_event_attributes
            )
            if started_attrs and hasattr(started_attrs, "input"):
                self._workflow_instance.start(started_attrs.input)

        self._decision_manager.handle_history_event(event)


def _failure_from_exception(e: Exception) -> Failure:
    stacktrace = "".join(traceback.format_exception(e))

    details = f"message: {str(e)}\nstacktrace: {stacktrace}"

    return Failure(
        reason=type(e).__name__,
        details=details.encode("utf-8"),
    )
