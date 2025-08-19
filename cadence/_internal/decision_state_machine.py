from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Sequence, Callable, Any, Tuple

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
        }
        return mapping.get(state, "Unknown")


class DecisionType(Enum):
    """Types of decisions that can be made by state machines."""
    
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


@dataclass
class StateTransition:
    """Represents a state transition with associated actions."""
    next_state: DecisionState
    action: Optional[Callable[['BaseDecisionStateMachine', history.HistoryEvent], None]] = None
    condition: Optional[Callable[['BaseDecisionStateMachine', history.HistoryEvent], bool]] = None


decision_state_transition_map = {
    "activity_task_scheduled_event_attributes": {
        "type": "initiated",
        "decision_type": DecisionType.ACTIVITY,
        "transition": StateTransition(
            next_state=DecisionState.INITIATED
        )
    },
    "activity_task_started_event_attributes": {
        "type": "started",
        "decision_type": DecisionType.ACTIVITY,
        "transition": StateTransition(
            next_state=DecisionState.STARTED
        )
    },
    "activity_task_completed_event_attributes": {
        "type": "completion",
        "decision_type": DecisionType.ACTIVITY,
        "transition": StateTransition(
            next_state=DecisionState.COMPLETED,
            action=lambda self, event: setattr(self, 'status', DecisionState.COMPLETED)
        )
    },
    "activity_task_failed_event_attributes": {
        "type": "completion",
        "decision_type": DecisionType.ACTIVITY,
        "transition": StateTransition(
            next_state=DecisionState.COMPLETED,
            action=lambda self, event: setattr(self, 'status', DecisionState.COMPLETED)
        )
    },
    "activity_task_timed_out_event_attributes": {
        "type": "completion",
        "decision_type": DecisionType.ACTIVITY,
        "transition": StateTransition(
            next_state=DecisionState.COMPLETED,
            action=lambda self, event: setattr(self, 'status', DecisionState.COMPLETED)
        )
    },
        "activity_task_cancel_requested_event_attributes": {
            "type": "cancel_initiated",
            "decision_type": DecisionType.CANCELLATION,
            "transition": StateTransition(
                next_state=None,
                action=lambda self, event: setattr(self, '_cancel_requested', True)
            )
        },
        "activity_task_canceled_event_attributes": {
            "type": "canceled",
            "decision_type": DecisionType.ACTIVITY,
            "transition": StateTransition(
                next_state=DecisionState.CANCELED_AFTER_INITIATED
            )
        },
        "request_cancel_activity_task_failed_event_attributes": {
            "type": "cancel_failed",
            "decision_type": DecisionType.CANCELLATION,
            "transition": StateTransition(
                next_state=None,
                action=lambda self, event: setattr(self, '_cancel_emitted', False)
            )
        },
    "timer_started_event_attributes": {
        "type": "initiated",
        "decision_type": DecisionType.TIMER,
        "transition": StateTransition(
            next_state=DecisionState.INITIATED
        )
    },
    "timer_fired_event_attributes": {
        "type": "completion",
        "decision_type": DecisionType.TIMER,
        "transition": StateTransition(
            next_state=DecisionState.COMPLETED,
            action=lambda self, event: setattr(self, 'status', DecisionState.COMPLETED)
        )
    },
    "timer_canceled_event_attributes": {
        "type": "canceled",
        "decision_type": DecisionType.TIMER,
        "transition": StateTransition(
            next_state=DecisionState.CANCELED_AFTER_INITIATED
        )
    },
        "cancel_timer_failed_event_attributes": {
            "type": "cancel_failed",
            "decision_type": DecisionType.CANCELLATION,
            "transition": StateTransition(
                next_state=None,
                action=lambda self, event: setattr(self, '_cancel_emitted', False)
            )
        },
    "start_child_workflow_execution_initiated_event_attributes": {
        "type": "initiated",
        "decision_type": DecisionType.CHILD_WORKFLOW,
        "transition": StateTransition(
            next_state=DecisionState.INITIATED
        )
    },
    "child_workflow_execution_started_event_attributes": {
        "type": "started",
        "decision_type": DecisionType.CHILD_WORKFLOW,
        "transition": StateTransition(
            next_state=DecisionState.STARTED
        )
    },
    "child_workflow_execution_completed_event_attributes": {
        "type": "completion",
        "decision_type": DecisionType.CHILD_WORKFLOW,
        "transition": StateTransition(
            next_state=DecisionState.COMPLETED,
            action=lambda self, event: setattr(self, 'status', DecisionState.COMPLETED)
        )
    },
    "child_workflow_execution_failed_event_attributes": {
        "type": "completion",
        "decision_type": DecisionType.CHILD_WORKFLOW,
        "transition": StateTransition(
            next_state=DecisionState.COMPLETED,
            action=lambda self, event: setattr(self, 'status', DecisionState.COMPLETED)
        )
    },
    "child_workflow_execution_timed_out_event_attributes": {
        "type": "completion",
        "decision_type": DecisionType.CHILD_WORKFLOW,
        "transition": StateTransition(
            next_state=DecisionState.COMPLETED,
            action=lambda self, event: setattr(self, 'status', DecisionState.COMPLETED)
        )
    },
    "child_workflow_execution_canceled_event_attributes": {
        "type": "canceled",
        "decision_type": DecisionType.CHILD_WORKFLOW,
        "transition": StateTransition(
            next_state=DecisionState.CANCELED_AFTER_INITIATED
        )
    },
    "child_workflow_execution_terminated_event_attributes": {
        "type": "canceled",
        "decision_type": DecisionType.CHILD_WORKFLOW,
        "transition": StateTransition(
            next_state=DecisionState.CANCELED_AFTER_INITIATED
        )
    },
    "start_child_workflow_execution_failed_event_attributes": {
        "type": "initiation_failed",
        "decision_type": DecisionType.CHILD_WORKFLOW,
        "transition": StateTransition(
            next_state=DecisionState.COMPLETED,
            action=lambda self, event: setattr(self, 'status', DecisionState.COMPLETED)
        )
    },
}


class BaseDecisionStateMachine:
    """Base class for state machines that may emit one or more decisions over time.

    Subclasses are responsible for mapping workflow history events into state
    transitions and producing the next set of decisions when queried.
    """

    def get_id(self) -> str:
        raise NotImplementedError

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

    def _default_initiated_action(self, event: history.HistoryEvent) -> None:
        """Default action for initiated events."""
        self.status = DecisionState.INITIATED
        event_id_field = self._get_event_id_field_name()
        setattr(self, event_id_field, event.event_id)

    def _default_started_action(self, event: history.HistoryEvent) -> None:
        """Default action for started events."""
        self.status = DecisionState.STARTED
        if hasattr(self, "started_event_id"):
            self.started_event_id = event.event_id

    def _default_completion_action(self, event: history.HistoryEvent, attr_name: str) -> None:
        """Default action for completion events."""
        self.status = DecisionState.COMPLETED

    def _default_cancel_action(self, event: history.HistoryEvent) -> None:
        """Default action for cancel events."""
        if self.status == DecisionState.INITIATED:
            self.status = DecisionState.CANCELED_AFTER_INITIATED
        elif self.status == DecisionState.STARTED:
            self.status = DecisionState.CANCELED_AFTER_INITIATED
        else:
            self.status = DecisionState.CANCELED_AFTER_INITIATED

    def _default_cancel_initiated_action(self, event: history.HistoryEvent) -> None:
        """Default action for cancel initiated events."""
        if hasattr(self, "_cancel_requested"):
            self._cancel_requested = True

    def _default_cancel_failed_action(self, event: history.HistoryEvent) -> None:
        """Default action for cancel failed events."""
        if hasattr(self, "_cancel_emitted"):
            self._cancel_emitted = False

    def handle_event(self, event: history.HistoryEvent, event_type: str) -> None:
        """Generic event handler that uses the global transition map to determine state changes.
        
        Args:
            event: The history event to process
            event_type: The type of event (e.g., 'initiated', 'started', 'completion', etc.)
        """
        if event_type == "initiated":
            self._handle_initiated_event(event)
        elif event_type == "started":
            self._handle_started_event(event)
        elif event_type == "completion":
            self._handle_completion_event(event)
        elif event_type == "cancel_initiated":
            self._handle_cancel_initiated_event(event)
        elif event_type == "cancel_failed":
            self._handle_cancel_failed_event(event)
        elif event_type == "canceled":
            self._handle_canceled_event(event)
        elif event_type == "initiation_failed":
            self._handle_initiation_failed_event(event)

    def _handle_initiated_event(self, event: history.HistoryEvent) -> None:
        """Handle initiated events using the global transition map."""
        attr_name = self._get_initiated_event_attr_name()
        id_field = self._get_id_field_name()
        
        if not self._should_handle_event(event, attr_name, id_field):
            return

        transition_info = decision_state_transition_map.get(attr_name)
        if transition_info and transition_info["type"] == "initiated":
            transition = transition_info["transition"]
            if transition.action:
                transition.action(self, event)
            else:
                self._default_initiated_action(event)

    def _handle_started_event(self, event: history.HistoryEvent) -> None:
        """Handle started events using the global transition map."""
        attr_name = self._get_started_event_attr_name()
        if not attr_name:  # Some decision types don't have started events
            return

        # Check if this event has the started attribute
        if hasattr(event, attr_name):
            # Determine the appropriate event ID field based on the decision type
            if attr_name == "activity_task_started_event_attributes":
                # Activity started events use scheduled_event_id
                event_id_field = "scheduled_event_id"
            elif attr_name == "child_workflow_execution_started_event_attributes":
                # Child workflow started events use initiated_event_id
                event_id_field = "initiated_event_id"
            else:
                event_id_field = self._get_event_id_field_name()
            
            if not self._should_handle_event_by_event_id(event, attr_name, event_id_field):
                return

            transition_info = decision_state_transition_map.get(attr_name)
            if transition_info and transition_info["type"] == "started":
                transition = transition_info["transition"]
                if transition.action:
                    transition.action(self, event)
                else:
                    self._default_started_action(event)

    def _handle_completion_event(self, event: history.HistoryEvent) -> None:
        """Handle completion events using the global transition map."""
        attr_names = self._get_completion_event_attr_names()

        for attr_name in attr_names:
            # Check if this event has the completion attribute
            if hasattr(event, attr_name):
                # Determine the appropriate event ID field based on the decision type
                if attr_name == "timer_fired_event_attributes":
                    # Timer completion events use started_event_id
                    event_id_field = "started_event_id"
                elif attr_name in ["activity_task_completed_event_attributes", "activity_task_failed_event_attributes", "activity_task_timed_out_event_attributes"]:
                    # Activity completion events use scheduled_event_id
                    event_id_field = "scheduled_event_id"
                elif attr_name in ["child_workflow_execution_completed_event_attributes", "child_workflow_execution_failed_event_attributes", "child_workflow_execution_timed_out_event_attributes"]:
                    # Child workflow completion events use initiated_event_id
                    event_id_field = "initiated_event_id"
                else:
                    # Default case
                    event_id_field = self._get_event_id_field_name()
                
                # Check if this event should be handled by this machine
                if self._should_handle_event_by_event_id(event, attr_name, event_id_field):
                    transition_info = decision_state_transition_map.get(attr_name)
                    if transition_info and transition_info["type"] == "completion":
                        transition = transition_info["transition"]
                        if transition.action:
                            transition.action(self, event)
                        else:
                            self._default_completion_action(event, attr_name)
                    break

    def _handle_cancel_initiated_event(self, event: history.HistoryEvent) -> None:
        """Handle cancel initiated events using the global transition map."""
        attr_name = self._get_cancel_initiated_event_attr_name()
        if not attr_name:  # Some decision types don't have cancel initiated events
            return

        id_field = self._get_id_field_name()
        if not self._should_handle_event(event, attr_name, id_field):
            return

        transition_info = decision_state_transition_map.get(attr_name)
        if transition_info and transition_info["type"] == "cancel_initiated":
            transition = transition_info["transition"]
            if transition.action:
                transition.action(self, event)
            else:
                self._default_cancel_initiated_action(event)

    def _handle_cancel_failed_event(self, event: history.HistoryEvent) -> None:
        """Handle cancel failed events using the global transition map."""
        attr_name = self._get_cancel_failed_event_attr_name()
        if not attr_name:  # Some decision types don't have cancel failed events
            return

        id_field = self._get_id_field_name()
        if not self._should_handle_event(event, attr_name, id_field):
            return

        transition_info = decision_state_transition_map.get(attr_name)
        if transition_info and transition_info["type"] == "cancel_failed":
            transition = transition_info["transition"]
            if transition.action:
                transition.action(self, event)
            else:
                self._default_cancel_failed_action(event)

    def _handle_canceled_event(self, event: history.HistoryEvent) -> None:
        """Handle canceled events using the global transition map."""
        attr_names = self._get_canceled_event_attr_names()

        for attr_name in attr_names:
            # Check if this event has the canceled attribute
            if hasattr(event, attr_name):
                # Determine the appropriate event ID field based on the decision type
                if attr_name == "timer_canceled_event_attributes":
                    # Timer canceled events use started_event_id
                    event_id_field = "started_event_id"
                elif attr_name == "activity_task_canceled_event_attributes":
                    # Activity canceled events use scheduled_event_id
                    event_id_field = "scheduled_event_id"
                elif attr_name in ["child_workflow_execution_canceled_event_attributes", "child_workflow_execution_terminated_event_attributes"]:
                    # Child workflow canceled events use initiated_event_id
                    event_id_field = "initiated_event_id"
                else:
                    # Default case
                    event_id_field = self._get_event_id_field_name()
                
                # Check if this event should be handled by this machine
                if self._should_handle_event_by_event_id(event, attr_name, event_id_field):
                    transition_info = decision_state_transition_map.get(attr_name)
                    if transition_info and transition_info["type"] == "canceled":
                        transition = transition_info["transition"]
                        if transition.action:
                            transition.action(self, event)
                        else:
                            self._default_cancel_action(event)
                    break

    def _handle_initiation_failed_event(self, event: history.HistoryEvent) -> None:
        """Handle initiation failed events using the global transition map."""
        # Default implementation - subclasses can override
        pass

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
            DecisionState.CANCELED_AFTER_INITIATED,
            DecisionState.CANCELED_AFTER_STARTED,
            DecisionState.COMPLETED_AFTER_CANCELLATION_DECISION_SENT,
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
            DecisionState.CANCELED_AFTER_INITIATED,
            DecisionState.CANCELED_AFTER_STARTED,
            DecisionState.COMPLETED_AFTER_CANCELLATION_DECISION_SENT,
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
            DecisionState.CANCELED_AFTER_INITIATED,
            DecisionState.CANCELED_AFTER_STARTED,
            DecisionState.COMPLETED_AFTER_CANCELLATION_DECISION_SENT,
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
        """Dispatch history event to typed handlers using the global transition map."""
        attr = event.WhichOneof("attributes")

        # Look up the event type from the global transition map
        transition_info = decision_state_transition_map.get(attr)
        if transition_info:
            event_type = transition_info["type"]
            # Route to all relevant machines using the new unified handle_event method
            for m in list(self.activities.values()):
                m.handle_event(event, event_type)
            for m in list(self.timers.values()):
                m.handle_event(event, event_type)
            for m in list(self.children.values()):
                m.handle_event(event, event_type)

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
