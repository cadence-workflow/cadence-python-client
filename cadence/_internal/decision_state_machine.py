from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Sequence

# Protobuf API types
from cadence.api.v1 import (
    decision_pb2 as decision,
    history_pb2 as history,
    common_pb2 as common,
)


class DecisionState(Enum):
    """Lifecycle states for a decision-producing state machine instance."""

    CREATED = 0
    DECISION_SENT = 1
    CANCELED_BEFORE_INITIATED = 2
    INITIATED = 3
    STARTED = 4
    CANCELED_AFTER_INITIATED = 5
    CANCELED_AFTER_STARTED = 6
    CANCELLATION_DECISION_SENT = 7
    COMPLETED_AFTER_CANCELLATION_DECISION_SENT = 8
    COMPLETED = 9
    FAILED = 10
    CANCELED = 11
    TIMED_OUT = 12

    @classmethod
    def to_string(cls, state: DecisionState) -> str:
        mapping = {
            DecisionState.CREATED: "Created",
            DecisionState.DECISION_SENT: "DecisionSent",
            DecisionState.CANCELED_BEFORE_INITIATED: "CanceledBeforeInitiated",
            DecisionState.INITIATED: "Initiated",
            DecisionState.STARTED: "Started",
            DecisionState.CANCELED_AFTER_INITIATED: "CanceledAfterInitiated",
            DecisionState.CANCELED_AFTER_STARTED: "CanceledAfterStarted",
            DecisionState.CANCELLATION_DECISION_SENT: "CancellationDecisionSent",
            DecisionState.COMPLETED_AFTER_CANCELLATION_DECISION_SENT: "CompletedAfterCancellationDecisionSent",
            DecisionState.COMPLETED: "Completed",
            DecisionState.FAILED: "Failed",
            DecisionState.CANCELED: "Canceled",
            DecisionState.TIMED_OUT: "TimedOut",
        }
        return mapping.get(state, "Unknown")


class DecisionType(Enum):
    ACTIVITY = 0
    CHILD_WORKFLOW = 1
    CANCELLATION = 2
    MARKER = 3
    TIMER = 4
    SIGNAL = 5
    UPSERT_SEARCH_ATTRIBUTES = 6

    @classmethod
    def to_string(cls, dt: DecisionType) -> str:
        mapping = {
            DecisionType.ACTIVITY: "Activity",
            DecisionType.CHILD_WORKFLOW: "ChildWorkflow",
            DecisionType.CANCELLATION: "Cancellation",
            DecisionType.MARKER: "Marker",
            DecisionType.TIMER: "Timer",
            DecisionType.SIGNAL: "Signal",
            DecisionType.UPSERT_SEARCH_ATTRIBUTES: "UpsertSearchAttributes",
        }
        return mapping.get(dt, "Unknown")


@dataclass(frozen=True)
class DecisionId:
    decision_type: DecisionType
    id: str

    def __str__(self) -> str:
        return (
            f"DecisionType: {DecisionType.to_string(self.decision_type)}, ID: {self.id}"
        )


class BaseDecisionStateMachine:
    """Base class for state machines that may emit one or more decisions over time.

    Subclasses are responsible for mapping workflow history events into state
    transitions and producing the next set of decisions when queried.
    """

    def get_id(self) -> str:
        raise NotImplementedError

    # Common patterns that can be overridden by subclasses
    def _get_initiated_event_attr_name(self) -> str:
        """Return the protobuf attribute name for initiated events."""
        raise NotImplementedError

    def _get_started_event_attr_name(self) -> str:
        """Return the protobuf attribute name for started events."""
        raise NotImplementedError

    def _get_completion_event_attr_names(self) -> List[str]:
        """Return the protobuf attribute names for completion events."""
        raise NotImplementedError

    def _get_cancel_initiated_event_attr_name(self) -> str:
        """Return the protobuf attribute name for cancel initiated events."""
        raise NotImplementedError

    def _get_cancel_failed_event_attr_name(self) -> str:
        """Return the protobuf attribute name for cancel failed events."""
        raise NotImplementedError

    def _get_canceled_event_attr_names(self) -> List[str]:
        """Return the protobuf attribute names for canceled events."""
        raise NotImplementedError

    def _get_id_field_name(self) -> str:
        """Return the field name used to identify this decision in events."""
        raise NotImplementedError

    def _get_event_id_field_name(self) -> str:
        """Return the field name used to track event IDs."""
        return "scheduled_event_id"  # Default, can be overridden

    def _should_handle_event(
        self, event: history.HistoryEvent, attr_name: str, id_field: str
    ) -> bool:
        """Generic check if this event should be handled by this machine."""
        attr = getattr(event, attr_name, None)
        if attr is None:
            return False

        # Check if the ID matches
        event_id = getattr(attr, id_field, None)
        machine_id = getattr(self, self._get_id_field_name(), None)
        return event_id == machine_id

    def _should_handle_event_by_event_id(
        self, event: history.HistoryEvent, attr_name: str, event_id_field: str
    ) -> bool:
        """Generic check if this event should be handled by this machine based on event ID."""
        attr = getattr(event, attr_name, None)
        if attr is None:
            return False

        # Check if the event ID matches our tracked event ID
        event_id = getattr(attr, event_id_field, None)
        tracked_event_id = getattr(self, self._get_event_id_field_name(), None)
        return event_id == tracked_event_id

    # Typed handlers with generic implementations
    def handle_initiated_event(self, event: history.HistoryEvent) -> None:
        """Generic initiated event handler."""
        attr_name = self._get_initiated_event_attr_name()
        id_field = self._get_id_field_name()

        if self._should_handle_event(event, attr_name, id_field):
            self.status = DecisionState.INITIATED
            # Store the event ID for future reference
            event_id_field = self._get_event_id_field_name()
            setattr(self, event_id_field, event.event_id)

    def handle_started_event(self, event: history.HistoryEvent) -> None:
        """Generic started event handler."""
        attr_name = self._get_started_event_attr_name()
        event_id_field = self._get_event_id_field_name()

        if self._should_handle_event_by_event_id(event, attr_name, event_id_field):
            self.status = DecisionState.STARTED
            # Store the started event ID if needed
            if hasattr(self, "started_event_id"):
                self.started_event_id = event.event_id

    def handle_completion_event(self, event: history.HistoryEvent) -> None:
        """Generic completion event handler."""
        attr_names = self._get_completion_event_attr_names()
        event_id_field = self._get_event_id_field_name()

        for attr_name in attr_names:
            if self._should_handle_event_by_event_id(event, attr_name, event_id_field):
                # Determine the completion state based on the attribute name
                if "completed" in attr_name:
                    self.status = DecisionState.COMPLETED
                elif "failed" in attr_name:
                    self.status = DecisionState.FAILED
                elif "timed_out" in attr_name:
                    self.status = DecisionState.TIMED_OUT
                elif "fired" in attr_name:
                    # Special case for timer fired events
                    self.status = DecisionState.COMPLETED
                break

    def handle_initiation_failed_event(self, event: history.HistoryEvent) -> None:
        """Generic initiation failed event handler."""
        # Default implementation - subclasses can override
        pass

    def handle_cancel_initiated_event(self, event: history.HistoryEvent) -> None:
        """Generic cancel initiated event handler."""
        attr_name = self._get_cancel_initiated_event_attr_name()
        id_field = self._get_id_field_name()

        if self._should_handle_event(event, attr_name, id_field):
            if hasattr(self, "_cancel_requested"):
                self._cancel_requested = True

    def handle_cancel_failed_event(self, event: history.HistoryEvent) -> None:
        """Generic cancel failed event handler."""
        attr_name = self._get_cancel_failed_event_attr_name()
        id_field = self._get_id_field_name()

        if self._should_handle_event(event, attr_name, id_field):
            if hasattr(self, "_cancel_emitted"):
                self._cancel_emitted = False

    def handle_canceled_event(self, event: history.HistoryEvent) -> None:
        """Generic canceled event handler."""
        attr_names = self._get_canceled_event_attr_names()
        event_id_field = self._get_event_id_field_name()

        for attr_name in attr_names:
            if self._should_handle_event_by_event_id(event, attr_name, event_id_field):
                self.status = DecisionState.CANCELED
                break

    def collect_pending_decisions(self) -> List[decision.Decision]:
        """Return any decisions that should be emitted now.

        Implementations must be idempotent: repeated calls without intervening
        state changes should return the same results (typically empty if already
        emitted for current state).
        """
        raise NotImplementedError


# Activity


@dataclass
class ActivityDecisionMachine(BaseDecisionStateMachine):
    """Tracks lifecycle of a single activity execution by activity_id."""

    activity_id: str
    schedule_attributes: decision.ScheduleActivityTaskDecisionAttributes
    status: DecisionState = DecisionState.CREATED
    scheduled_event_id: Optional[int] = None
    started_event_id: Optional[int] = None
    _schedule_emitted: bool = False
    _cancel_requested: bool = False
    _cancel_emitted: bool = False

    def get_id(self) -> str:
        return self.activity_id

    # Implement abstract methods for generic handlers
    def _get_initiated_event_attr_name(self) -> str:
        return "activity_task_scheduled_event_attributes"

    def _get_started_event_attr_name(self) -> str:
        return "activity_task_started_event_attributes"

    def _get_completion_event_attr_names(self) -> List[str]:
        return [
            "activity_task_completed_event_attributes",
            "activity_task_failed_event_attributes",
            "activity_task_timed_out_event_attributes",
        ]

    def _get_cancel_initiated_event_attr_name(self) -> str:
        return "activity_task_cancel_requested_event_attributes"

    def _get_cancel_failed_event_attr_name(self) -> str:
        return "request_cancel_activity_task_failed_event_attributes"

    def _get_canceled_event_attr_names(self) -> List[str]:
        return ["activity_task_canceled_event_attributes"]

    def _get_id_field_name(self) -> str:
        return "activity_id"

    def _get_event_id_field_name(self) -> str:
        return "scheduled_event_id"

    def collect_pending_decisions(self) -> List[decision.Decision]:
        decisions: List[decision.Decision] = []

        if self.status is DecisionState.CREATED and not self._schedule_emitted:
            # Emit initial schedule decision
            decisions.append(
                decision.Decision(
                    schedule_activity_task_decision_attributes=self.schedule_attributes
                )
            )
            self._schedule_emitted = True

        if (
            self._cancel_requested
            and not self._cancel_emitted
            and not self.is_terminal()
        ):
            # Emit cancel request
            decisions.append(
                decision.Decision(
                    request_cancel_activity_task_decision_attributes=decision.RequestCancelActivityTaskDecisionAttributes(
                        activity_id=self.activity_id
                    )
                )
            )
            self._cancel_emitted = True

        return decisions

    def request_cancel(self) -> None:
        if not self.is_terminal():
            self._cancel_requested = True

    def is_terminal(self) -> bool:
        return self.status in (
            DecisionState.COMPLETED,
            DecisionState.FAILED,
            DecisionState.CANCELED,
            DecisionState.TIMED_OUT,
        )


# Timer


@dataclass
class TimerDecisionMachine(BaseDecisionStateMachine):
    """Tracks lifecycle of a single workflow timer by timer_id."""

    timer_id: str
    start_attributes: decision.StartTimerDecisionAttributes
    status: DecisionState = DecisionState.CREATED
    started_event_id: Optional[int] = None
    _start_emitted: bool = False
    _cancel_requested: bool = False
    _cancel_emitted: bool = False

    def get_id(self) -> str:
        return self.timer_id

    # Implement abstract methods for generic handlers
    def _get_initiated_event_attr_name(self) -> str:
        return "timer_started_event_attributes"

    def _get_started_event_attr_name(self) -> str:
        return ""  # Timers don't have a separate started event

    def _get_completion_event_attr_names(self) -> List[str]:
        return ["timer_fired_event_attributes"]

    def _get_cancel_initiated_event_attr_name(self) -> str:
        return ""  # Timers don't have cancel initiated events

    def _get_cancel_failed_event_attr_name(self) -> str:
        return "cancel_timer_failed_event_attributes"

    def _get_canceled_event_attr_names(self) -> List[str]:
        return ["timer_canceled_event_attributes"]

    def _get_id_field_name(self) -> str:
        return "timer_id"

    def _get_event_id_field_name(self) -> str:
        return "started_event_id"

    # Override started event handler since timers don't have separate started events
    def handle_started_event(self, event: history.HistoryEvent) -> None:
        # Timers don't have a separate started beyond TimerStarted
        pass

    # Override cancel initiated handler since timers don't have this event
    def handle_cancel_initiated_event(self, event: history.HistoryEvent) -> None:
        # Timers don't have cancel initiated events
        pass

    def collect_pending_decisions(self) -> List[decision.Decision]:
        decisions: List[decision.Decision] = []

        if self.status is DecisionState.CREATED and not self._start_emitted:
            decisions.append(
                decision.Decision(start_timer_decision_attributes=self.start_attributes)
            )
            self._start_emitted = True

        if (
            self._cancel_requested
            and not self._cancel_emitted
            and not self.is_terminal()
        ):
            decisions.append(
                decision.Decision(
                    cancel_timer_decision_attributes=decision.CancelTimerDecisionAttributes(
                        timer_id=self.timer_id
                    )
                )
            )
            self._cancel_emitted = True

        return decisions

    def request_cancel(self) -> None:
        if not self.is_terminal():
            self._cancel_requested = True

    def is_terminal(self) -> bool:
        return self.status in (
            DecisionState.COMPLETED,
            DecisionState.CANCELED,
            DecisionState.FAILED,
            DecisionState.TIMED_OUT,
        )


# Child Workflow


@dataclass
class ChildWorkflowDecisionMachine(BaseDecisionStateMachine):
    """Tracks lifecycle of a child workflow start/cancel by client-provided id.

    Cadence history references child workflows via initiated event IDs. For simplicity,
    we track by a client-provided identifier (e.g., a unique string) that must map
    to attributes.worklow_id when possible.
    """

    client_id: str
    start_attributes: decision.StartChildWorkflowExecutionDecisionAttributes
    status: DecisionState = DecisionState.CREATED
    initiated_event_id: Optional[int] = None
    started_event_id: Optional[int] = None
    _start_emitted: bool = False
    _cancel_requested: bool = False
    _cancel_emitted: bool = False

    def get_id(self) -> str:
        return self.client_id

    # Implement abstract methods for generic handlers
    def _get_initiated_event_attr_name(self) -> str:
        return "start_child_workflow_execution_initiated_event_attributes"

    def _get_started_event_attr_name(self) -> str:
        return "child_workflow_execution_started_event_attributes"

    def _get_completion_event_attr_names(self) -> List[str]:
        return [
            "child_workflow_execution_completed_event_attributes",
            "child_workflow_execution_failed_event_attributes",
            "child_workflow_execution_timed_out_event_attributes",
        ]

    def _get_cancel_initiated_event_attr_name(self) -> str:
        return ""  # Child workflows don't have cancel initiated events

    def _get_cancel_failed_event_attr_name(self) -> str:
        return ""  # Child workflows don't have cancel failed events

    def _get_canceled_event_attr_names(self) -> List[str]:
        return [
            "child_workflow_execution_canceled_event_attributes",
            "child_workflow_execution_terminated_event_attributes",
        ]

    def _get_id_field_name(self) -> str:
        return "workflow_id"

    def _get_event_id_field_name(self) -> str:
        return "initiated_event_id"

    # Override the generic ID check for child workflows since we need to check workflow_id
    def _should_handle_event(
        self, event: history.HistoryEvent, attr_name: str, id_field: str
    ) -> bool:
        """Override for child workflows to check workflow_id instead of client_id."""
        attr = getattr(event, attr_name, None)
        if attr is None:
            return False

        # For child workflows, check if the workflow_id matches
        event_workflow_id = getattr(attr, id_field, None)
        machine_workflow_id = self.start_attributes.workflow_id
        return event_workflow_id == machine_workflow_id

    # Override cancel initiated handler since child workflows don't have this event
    def handle_cancel_initiated_event(self, event: history.HistoryEvent) -> None:
        # Child workflows don't have cancel initiated events
        pass

    # Override cancel failed handler since child workflows don't have this event
    def handle_cancel_failed_event(self, event: history.HistoryEvent) -> None:
        # Child workflows don't have cancel failed events
        pass

    # Override initiation failed handler for child workflows
    def handle_initiation_failed_event(self, event: history.HistoryEvent) -> None:
        a = getattr(
            event, "start_child_workflow_execution_failed_event_attributes", None
        )
        if a is not None and (
            (
                hasattr(a, "initiated_event_id")
                and self.initiated_event_id
                and a.initiated_event_id == self.initiated_event_id
            )
            or a.workflow_id == self.start_attributes.workflow_id
        ):
            self.status = DecisionState.FAILED

    def collect_pending_decisions(self) -> List[decision.Decision]:
        decisions: List[decision.Decision] = []

        if self.status is DecisionState.CREATED and not self._start_emitted:
            decisions.append(
                decision.Decision(
                    start_child_workflow_execution_decision_attributes=self.start_attributes
                )
            )
            self._start_emitted = True

        if (
            self._cancel_requested
            and not self._cancel_emitted
            and not self.is_terminal()
        ):
            # Request cancel of the child workflow via external cancel with child_workflow_only
            decisions.append(
                decision.Decision(
                    request_cancel_external_workflow_execution_decision_attributes=decision.RequestCancelExternalWorkflowExecutionDecisionAttributes(
                        domain=self.start_attributes.domain,
                        workflow_execution=common.WorkflowExecution(
                            workflow_id=self.start_attributes.workflow_id
                        ),
                        child_workflow_only=True,
                    )
                )
            )
            self._cancel_emitted = True
        return decisions

    def request_cancel(self) -> None:
        if not self.is_terminal():
            self._cancel_requested = True

    def is_terminal(self) -> bool:
        return self.status in (
            DecisionState.COMPLETED,
            DecisionState.FAILED,
            DecisionState.CANCELED,
            DecisionState.TIMED_OUT,
        )


@dataclass
class DecisionManager:
    """Aggregates multiple decision state machines and coordinates decisions.

    Typical flow per decision task:
    - Instantiate/update state machines based on application intent and incoming history
    - Call collect_pending_decisions() to build the decisions list
    - Submit via RespondDecisionTaskCompleted
    """

    activities: Dict[str, ActivityDecisionMachine] = field(default_factory=dict)
    timers: Dict[str, TimerDecisionMachine] = field(default_factory=dict)
    children: Dict[str, ChildWorkflowDecisionMachine] = field(default_factory=dict)

    # ----- Activity API -----

    def schedule_activity(
        self, activity_id: str, attrs: decision.ScheduleActivityTaskDecisionAttributes
    ) -> ActivityDecisionMachine:
        machine = self.activities.get(activity_id)
        if machine is None or machine.is_terminal():
            machine = ActivityDecisionMachine(
                activity_id=activity_id, schedule_attributes=attrs
            )
            self.activities[activity_id] = machine
        return machine

    def request_cancel_activity(self, activity_id: str) -> None:
        machine = self.activities.get(activity_id)
        if machine is not None:
            machine.request_cancel()

    # ----- Timer API -----

    def start_timer(
        self, timer_id: str, attrs: decision.StartTimerDecisionAttributes
    ) -> TimerDecisionMachine:
        machine = self.timers.get(timer_id)
        if machine is None or machine.is_terminal():
            machine = TimerDecisionMachine(timer_id=timer_id, start_attributes=attrs)
            self.timers[timer_id] = machine
        return machine

    def cancel_timer(self, timer_id: str) -> None:
        machine = self.timers.get(timer_id)
        if machine is not None:
            machine.request_cancel()

    # ----- Child Workflow API -----

    def start_child_workflow(
        self,
        client_id: str,
        attrs: decision.StartChildWorkflowExecutionDecisionAttributes,
    ) -> ChildWorkflowDecisionMachine:
        machine = self.children.get(client_id)
        if machine is None or machine.is_terminal():
            machine = ChildWorkflowDecisionMachine(
                client_id=client_id, start_attributes=attrs
            )
            self.children[client_id] = machine
        return machine

    def cancel_child_workflow(self, client_id: str) -> None:
        machine = self.children.get(client_id)
        if machine is not None:
            machine.request_cancel()

    # ----- History routing -----

    def handle_history_event(self, event: history.HistoryEvent) -> None:
        """Dispatch history event to typed handlers, Go-style."""
        attr = event.WhichOneof("attributes")

        # Initiated
        if attr in (
            "activity_task_scheduled_event_attributes",
            "timer_started_event_attributes",
            "start_child_workflow_execution_initiated_event_attributes",
        ):
            for m in list(self.activities.values()):
                m.handle_initiated_event(event)
            for m in list(self.timers.values()):
                m.handle_initiated_event(event)
            for m in list(self.children.values()):
                m.handle_initiated_event(event)
            return

        # Started
        if attr in (
            "activity_task_started_event_attributes",
            "child_workflow_execution_started_event_attributes",
        ):
            for m in list(self.activities.values()):
                m.handle_started_event(event)
            for m in list(self.children.values()):
                m.handle_started_event(event)
            return

        # Completion-like
        if attr in (
            "activity_task_completed_event_attributes",
            "activity_task_failed_event_attributes",
            "activity_task_timed_out_event_attributes",
            "timer_fired_event_attributes",
            "child_workflow_execution_completed_event_attributes",
            "child_workflow_execution_failed_event_attributes",
            "child_workflow_execution_timed_out_event_attributes",
        ):
            for m in list(self.activities.values()):
                m.handle_completion_event(event)
            for m in list(self.timers.values()):
                m.handle_completion_event(event)
            for m in list(self.children.values()):
                m.handle_completion_event(event)
            return

        # Cancel-initiated / cancel-failed / canceled
        if attr in ("activity_task_cancel_requested_event_attributes",):
            for m in list(self.activities.values()):
                m.handle_cancel_initiated_event(event)
            return

        if attr in (
            "request_cancel_activity_task_failed_event_attributes",
            "cancel_timer_failed_event_attributes",
        ):
            for m in list(self.activities.values()):
                m.handle_cancel_failed_event(event)
            for m in list(self.timers.values()):
                m.handle_cancel_failed_event(event)
            return

        if attr in (
            "activity_task_canceled_event_attributes",
            "timer_canceled_event_attributes",
            "child_workflow_execution_canceled_event_attributes",
            "child_workflow_execution_terminated_event_attributes",
        ):
            for m in list(self.activities.values()):
                m.handle_canceled_event(event)
            for m in list(self.timers.values()):
                m.handle_canceled_event(event)
            for m in list(self.children.values()):
                m.handle_canceled_event(event)
            return

        # Initiation failed
        if attr in ("start_child_workflow_execution_failed_event_attributes",):
            for m in list(self.children.values()):
                m.handle_initiation_failed_event(event)
            return

    # ----- Decision aggregation -----

    def collect_pending_decisions(self) -> List[decision.Decision]:
        decisions: List[decision.Decision] = []

        # Activities
        for machine in list(self.activities.values()):
            decisions.extend(machine.collect_pending_decisions())

        # Timers
        for machine in list(self.timers.values()):
            decisions.extend(machine.collect_pending_decisions())

        # Children
        for machine in list(self.children.values()):
            decisions.extend(machine.collect_pending_decisions())

        return decisions
