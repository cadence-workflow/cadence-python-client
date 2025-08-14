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


class MachineStatus(Enum):
    """Lifecycle states for a decision-producing state machine instance."""

    CREATED = auto()
    SCHEDULED = auto()
    STARTED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELED = auto()
    TIMED_OUT = auto()


class DecisionState(Enum):
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


class DecisionType(Enum):
    ACTIVITY = 0
    CHILD_WORKFLOW = 1
    CANCELLATION = 2
    MARKER = 3
    TIMER = 4
    SIGNAL = 5
    UPSERT_SEARCH_ATTRIBUTES = 6


# Event name constants (used by Go state machine; provided for parity/testing/logs)
EVENT_CANCEL = "cancel"
EVENT_DECISION_SENT = "handleDecisionSent"
EVENT_INITIATED = "handleInitiatedEvent"
EVENT_INITIATION_FAILED = "handleInitiationFailedEvent"
EVENT_STARTED = "handleStartedEvent"
EVENT_COMPLETION = "handleCompletionEvent"
EVENT_CANCEL_INITIATED = "handleCancelInitiatedEvent"
EVENT_CANCEL_FAILED = "handleCancelFailedEvent"
EVENT_CANCELED = "handleCanceledEvent"


# Marker names
SIDE_EFFECT_MARKER_NAME = "SideEffect"
VERSION_MARKER_NAME = "Version"
LOCAL_ACTIVITY_MARKER_NAME = "LocalActivity"
MUTABLE_SIDE_EFFECT_MARKER_NAME = "MutableSideEffect"


def decision_state_to_string(state: DecisionState) -> str:
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


def decision_type_to_string(dt: DecisionType) -> str:
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
        return f"DecisionType: {decision_type_to_string(self.decision_type)}, ID: {self.id}"


class DecisionStateMachine:
    """Base class for state machines that may emit one or more decisions over time.

    Subclasses are responsible for mapping workflow history events into state
    transitions and producing the next set of decisions when queried.
    """

    def get_id(self) -> str:
        raise NotImplementedError

    # Typed handlers (Go-parity naming semantics)
    def handle_initiated_event(self, event: history.HistoryEvent) -> None:
        pass

    def handle_started_event(self, event: history.HistoryEvent) -> None:
        pass

    def handle_completion_event(self, event: history.HistoryEvent) -> None:
        pass

    def handle_initiation_failed_event(self, event: history.HistoryEvent) -> None:
        pass

    def handle_cancel_initiated_event(self, event: history.HistoryEvent) -> None:
        pass

    def handle_cancel_failed_event(self, event: history.HistoryEvent) -> None:
        pass

    def handle_canceled_event(self, event: history.HistoryEvent) -> None:
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
class ActivityDecisionMachine(DecisionStateMachine):
    """Tracks lifecycle of a single activity execution by activity_id."""

    activity_id: str
    schedule_attributes: decision.ScheduleActivityTaskDecisionAttributes
    status: MachineStatus = MachineStatus.CREATED
    scheduled_event_id: Optional[int] = None
    started_event_id: Optional[int] = None
    _schedule_emitted: bool = False
    _cancel_requested: bool = False
    _cancel_emitted: bool = False

    def get_id(self) -> str:
        return self.activity_id

    def handle_initiated_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "activity_task_scheduled_event_attributes", None)
        if a is not None and a.activity_id == self.activity_id:
            self.status = MachineStatus.SCHEDULED
            self.scheduled_event_id = event.event_id

    def handle_started_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "activity_task_started_event_attributes", None)
        if a is not None and self.scheduled_event_id and a.scheduled_event_id == self.scheduled_event_id:
            self.status = MachineStatus.STARTED
            self.started_event_id = event.event_id

    def handle_completion_event(self, event: history.HistoryEvent) -> None:
        if getattr(event, "activity_task_completed_event_attributes", None) is not None:
            a = event.activity_task_completed_event_attributes
            if self.scheduled_event_id and a.scheduled_event_id == self.scheduled_event_id:
                self.status = MachineStatus.COMPLETED
        elif getattr(event, "activity_task_failed_event_attributes", None) is not None:
            a = event.activity_task_failed_event_attributes
            if self.scheduled_event_id and a.scheduled_event_id == self.scheduled_event_id:
                self.status = MachineStatus.FAILED
        elif getattr(event, "activity_task_timed_out_event_attributes", None) is not None:
            a = event.activity_task_timed_out_event_attributes
            if self.scheduled_event_id and a.scheduled_event_id == self.scheduled_event_id:
                self.status = MachineStatus.TIMED_OUT

    def handle_cancel_initiated_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "activity_task_cancel_requested_event_attributes", None)
        if a is not None and a.activity_id == self.activity_id:
            self._cancel_requested = True

    def handle_cancel_failed_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "request_cancel_activity_task_failed_event_attributes", None)
        if a is not None and a.activity_id == self.activity_id:
            # allow future cancel retry
            self._cancel_emitted = False

    def handle_canceled_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "activity_task_canceled_event_attributes", None)
        if a is not None and self.scheduled_event_id and a.scheduled_event_id == self.scheduled_event_id:
            self.status = MachineStatus.CANCELED

    def collect_pending_decisions(self) -> List[decision.Decision]:
        decisions: List[decision.Decision] = []

        if self.status is MachineStatus.CREATED and not self._schedule_emitted:
            # Emit initial schedule decision
            decisions.append(
                decision.Decision(
                    schedule_activity_task_decision_attributes=self.schedule_attributes
                )
            )
            self._schedule_emitted = True

        if self._cancel_requested and not self._cancel_emitted and not self.is_terminal():
            # Emit cancel request
            decisions.append(
                decision.Decision(
                    request_cancel_activity_task_decision_attributes=
                    decision.RequestCancelActivityTaskDecisionAttributes(
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
            MachineStatus.COMPLETED,
            MachineStatus.FAILED,
            MachineStatus.CANCELED,
            MachineStatus.TIMED_OUT,
        )


# Timer


@dataclass
class TimerDecisionMachine(DecisionStateMachine):
    """Tracks lifecycle of a single workflow timer by timer_id."""

    timer_id: str
    start_attributes: decision.StartTimerDecisionAttributes
    status: MachineStatus = MachineStatus.CREATED
    started_event_id: Optional[int] = None
    _start_emitted: bool = False
    _cancel_requested: bool = False
    _cancel_emitted: bool = False

    def get_id(self) -> str:
        return self.timer_id

    def handle_initiated_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "timer_started_event_attributes", None)
        if a is not None and a.timer_id == self.timer_id:
            self.status = MachineStatus.SCHEDULED
            self.started_event_id = event.event_id

    def handle_started_event(self, event: history.HistoryEvent) -> None:
        # Timers don't have a separate started beyond TimerStarted
        pass

    def handle_completion_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "timer_fired_event_attributes", None)
        if a is not None and self.started_event_id and a.started_event_id == self.started_event_id:
            self.status = MachineStatus.COMPLETED

    def handle_canceled_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "timer_canceled_event_attributes", None)
        if a is not None and self.started_event_id and a.started_event_id == self.started_event_id:
            self.status = MachineStatus.CANCELED

    def handle_cancel_failed_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "cancel_timer_failed_event_attributes", None)
        if a is not None and a.timer_id == self.timer_id:
            self._cancel_emitted = False

    def collect_pending_decisions(self) -> List[decision.Decision]:
        decisions: List[decision.Decision] = []

        if self.status is MachineStatus.CREATED and not self._start_emitted:
            decisions.append(
                decision.Decision(
                    start_timer_decision_attributes=self.start_attributes
                )
            )
            self._start_emitted = True

        if self._cancel_requested and not self._cancel_emitted and not self.is_terminal():
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
            MachineStatus.COMPLETED,
            MachineStatus.CANCELED,
            MachineStatus.FAILED,
            MachineStatus.TIMED_OUT,
        )


# Child Workflow


@dataclass
class ChildWorkflowDecisionMachine(DecisionStateMachine):
    """Tracks lifecycle of a child workflow start/cancel by client-provided id.

    Cadence history references child workflows via initiated event IDs. For simplicity,
    we track by a client-provided identifier (e.g., a unique string) that must map
    to attributes.worklow_id when possible.
    """

    client_id: str
    start_attributes: decision.StartChildWorkflowExecutionDecisionAttributes
    status: MachineStatus = MachineStatus.CREATED
    initiated_event_id: Optional[int] = None
    started_event_id: Optional[int] = None
    _start_emitted: bool = False
    _cancel_requested: bool = False
    _cancel_emitted: bool = False

    def get_id(self) -> str:
        return self.client_id

    def handle_initiated_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "start_child_workflow_execution_initiated_event_attributes", None)
        if a is not None and a.workflow_id == self.start_attributes.workflow_id:
            self.status = MachineStatus.SCHEDULED
            self.initiated_event_id = event.event_id

    def handle_started_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "child_workflow_execution_started_event_attributes", None)
        if a is not None and self.initiated_event_id and a.initiated_event_id == self.initiated_event_id:
            self.status = MachineStatus.STARTED
            self.started_event_id = event.event_id

    def handle_completion_event(self, event: history.HistoryEvent) -> None:
        if getattr(event, "child_workflow_execution_completed_event_attributes", None) is not None:
            a = event.child_workflow_execution_completed_event_attributes
            if self.initiated_event_id and a.initiated_event_id == self.initiated_event_id:
                self.status = MachineStatus.COMPLETED
        elif getattr(event, "child_workflow_execution_failed_event_attributes", None) is not None:
            a = event.child_workflow_execution_failed_event_attributes
            if self.initiated_event_id and a.initiated_event_id == self.initiated_event_id:
                self.status = MachineStatus.FAILED
        elif getattr(event, "child_workflow_execution_timed_out_event_attributes", None) is not None:
            a = event.child_workflow_execution_timed_out_event_attributes
            if self.initiated_event_id and a.initiated_event_id == self.initiated_event_id:
                self.status = MachineStatus.TIMED_OUT

    def handle_canceled_event(self, event: history.HistoryEvent) -> None:
        if getattr(event, "child_workflow_execution_canceled_event_attributes", None) is not None:
            a = event.child_workflow_execution_canceled_event_attributes
            if self.initiated_event_id and a.initiated_event_id == self.initiated_event_id:
                self.status = MachineStatus.CANCELED
        elif getattr(event, "child_workflow_execution_terminated_event_attributes", None) is not None:
            a = event.child_workflow_execution_terminated_event_attributes
            if self.initiated_event_id and a.initiated_event_id == self.initiated_event_id:
                self.status = MachineStatus.CANCELED

    def handle_initiation_failed_event(self, event: history.HistoryEvent) -> None:
        a = getattr(event, "start_child_workflow_execution_failed_event_attributes", None)
        if a is not None and (
            (hasattr(a, "initiated_event_id") and self.initiated_event_id and a.initiated_event_id == self.initiated_event_id)
            or a.workflow_id == self.start_attributes.workflow_id
        ):
            self.status = MachineStatus.FAILED

    def collect_pending_decisions(self) -> List[decision.Decision]:
        decisions: List[decision.Decision] = []

        if self.status is MachineStatus.CREATED and not self._start_emitted:
            decisions.append(
                decision.Decision(
                    start_child_workflow_execution_decision_attributes=self.start_attributes
                )
            )
            self._start_emitted = True

        if self._cancel_requested and not self._cancel_emitted and not self.is_terminal():
            # Request cancel of the child workflow via external cancel with child_workflow_only
            decisions.append(
                decision.Decision(
                    request_cancel_external_workflow_execution_decision_attributes=
                    decision.RequestCancelExternalWorkflowExecutionDecisionAttributes(
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
            MachineStatus.COMPLETED,
            MachineStatus.FAILED,
            MachineStatus.CANCELED,
            MachineStatus.TIMED_OUT,
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
            machine = ActivityDecisionMachine(activity_id=activity_id, schedule_attributes=attrs)
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
        self, client_id: str, attrs: decision.StartChildWorkflowExecutionDecisionAttributes
    ) -> ChildWorkflowDecisionMachine:
        machine = self.children.get(client_id)
        if machine is None or machine.is_terminal():
            machine = ChildWorkflowDecisionMachine(client_id=client_id, start_attributes=attrs)
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


