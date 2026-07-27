import asyncio
import logging
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Type, ClassVar, List, Iterator

from cadence._internal.workflow.statemachine.activity_state_machine import (
    activity_events,
    ActivityStateMachine,
)
from cadence._internal.workflow.statemachine.child_workflow_execution_state_machine import (
    child_workflow_events,
    ChildWorkflowExecutionStateMachine,
)
from cadence._internal.workflow.statemachine.completion_state_machine import (
    COMPLETION_ID,
    CompletionStateMachine,
)
from cadence._internal.workflow.statemachine.decision_state_machine import (
    CancelFn,
    DecisionId,
    DecisionStateMachine,
    DecisionType,
    DecisionFuture,
    T,
)
from cadence._internal.workflow.statemachine.event_dispatcher import (
    EventDispatcher,
    Action,
    resolve_id_attr,
)
from cadence._internal.workflow.statemachine.marker_state_machine import (
    encode_marker_header,
    marker_context_id,
    marker_decision_id,
    KNOWN_MARKER_NAMES,
    MARKER_HEADER_KEY,
    marker_events,
    MarkerStateMachine,
)
from cadence._internal.workflow.statemachine.nondeterminism import DeterminismTracker
from cadence._internal.workflow.statemachine.cancellation import is_immediate_cancel
from cadence._internal.workflow.statemachine.signal_external_workflow_state_machine import (
    signal_external_events,
    SignalExternalWorkflowStateMachine,
)
from cadence._internal.workflow.statemachine.timer_state_machine import (
    TimerStateMachine,
    timer_events,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload, WorkflowExecution

logger = logging.getLogger(__name__)

DecisionAlias = tuple[DecisionType, str | int]


def _consume_future_exception(future: asyncio.Future[Any]) -> None:
    if not future.cancelled():
        future.exception()


@dataclass(frozen=True)
class EventDispatch:
    decision_type: DecisionType
    action: Action


def _create_dispatch_map(
    dispatchers: dict[DecisionType, EventDispatcher],
) -> dict[Type, EventDispatch]:
    result: dict[Type, EventDispatch] = {}
    for decision_type, dispatcher in dispatchers.items():
        for event_type, action in dispatcher.handlers.items():
            if event_type in result:
                raise ValueError(
                    f"Received duplicate registration for {event_type}: {decision_type} and {result[event_type].decision_type}"
                )
            result[event_type] = EventDispatch(decision_type, action)

    return result


class DecisionManager:
    """Aggregates multiple decision state machines and coordinates decisions.

    Typical flow per decision task:
    - Instantiate/update state machines based on application intent and incoming history
    - Call collect_pending_decisions() to build the decisions list
    - Submit via RespondDecisionTaskCompleted
    """

    type_to_action: ClassVar[Dict[Type, EventDispatch]] = _create_dispatch_map(
        {
            DecisionType.ACTIVITY: activity_events,
            DecisionType.TIMER: timer_events,
            DecisionType.CHILD_WORKFLOW: child_workflow_events,
            DecisionType.SIGNAL: signal_external_events,
            DecisionType.MARKER: marker_events,
        }
    )

    def __init__(self, event_loop: asyncio.AbstractEventLoop):
        self._event_loop = event_loop
        self._id_counter = 0
        self._determinism_tracker = DeterminismTracker()
        self._replaying = False
        self._recorded_marker_details: Dict[DecisionId, Payload] = {}
        self.state_machines: OrderedDict[DecisionId, DecisionStateMachine] = (
            OrderedDict()
        )
        self.aliases: Dict[DecisionAlias, DecisionStateMachine] = dict()

    # ----- Activity API -----

    def schedule_activity(
        self, attrs: decision.ScheduleActivityTaskDecisionAttributes
    ) -> asyncio.Future[Payload]:
        attrs.activity_id = self._next_id()
        if self._replaying:
            self._determinism_tracker.validate_action(attrs)
        decision_id = DecisionId(DecisionType.ACTIVITY, attrs.activity_id)
        future: DecisionFuture[Payload] = self._create_future(decision_id)
        machine = ActivityStateMachine(attrs, future)
        self._add_state_machine(machine)

        return future

    # ----- Timer API -----

    def start_timer(
        self, attrs: decision.StartTimerDecisionAttributes
    ) -> asyncio.Future[None]:
        attrs.timer_id = self._next_id()
        if self._replaying:
            self._determinism_tracker.validate_action(attrs)
        decision_id = DecisionId(DecisionType.TIMER, attrs.timer_id)
        future: DecisionFuture[None] = self._create_future(decision_id)
        machine = TimerStateMachine(attrs, future)
        self._add_state_machine(machine)

        return future

    # ----- Child Workflow API -----
    def schedule_child_workflow(
        self,
        attrs: decision.StartChildWorkflowExecutionDecisionAttributes,
        *,
        parent_workflow_run_id: str,
    ) -> tuple[DecisionFuture[WorkflowExecution], DecisionFuture[Payload]]:

        if not attrs.workflow_id:
            attrs.workflow_id = f"{parent_workflow_run_id}_{self._next_id()}"
        if self._replaying:
            self._determinism_tracker.validate_action(attrs)
        decision_id = DecisionId(DecisionType.CHILD_WORKFLOW, attrs.workflow_id)
        execution: DecisionFuture[WorkflowExecution] = self._create_future(decision_id)
        execution.add_done_callback(_consume_future_exception)
        result: DecisionFuture[Payload] = self._create_future(decision_id)
        machine = ChildWorkflowExecutionStateMachine(attrs, execution, result)
        self._add_state_machine(machine)
        return execution, result

    # ----- Signal External Workflow API -----

    def signal_external_workflow(
        self,
        attrs: decision.SignalExternalWorkflowExecutionDecisionAttributes,
    ) -> asyncio.Future[None]:
        signal_id = self._next_id()
        attrs.control = signal_id.encode("utf-8")
        if self._replaying:
            self._determinism_tracker.validate_action(attrs)
        decision_id = DecisionId(DecisionType.SIGNAL, signal_id)
        future: DecisionFuture[None] = self._create_future(decision_id)
        machine = SignalExternalWorkflowStateMachine(attrs, future, signal_id)
        self._add_state_machine(machine)
        return future

    # ----- Marker API -----

    def record_marker(
        self,
        attrs: decision.RecordMarkerDecisionAttributes,
    ) -> Payload:
        if not attrs.marker_name:
            raise ValueError("marker_name is required")
        context_id = self._next_id()

        # Metadata (the context_id) goes in the Header; Details stays the raw user payload.
        # The header is set in-place so the state machine carries it on the wire.
        attrs.header.fields[MARKER_HEADER_KEY].CopyFrom(
            encode_marker_header(context_id)
        )

        marker_id = marker_decision_id(attrs.marker_name, context_id)
        result = Payload(data=attrs.details.data)

        if self._replaying:
            self._determinism_tracker.validate_action(attrs)
            history_value = self._recorded_marker_details.get(marker_id)
            if history_value is not None:
                result = Payload(data=history_value.data)

        machine = MarkerStateMachine(attrs, attrs.marker_name, context_id)
        self._add_state_machine(machine)
        return result

    # ----- Workflow API -----
    def complete_workflow(self, decision: decision.Decision) -> None:
        if self._replaying:
            attr = decision.WhichOneof("attributes")
            decision_attributes = getattr(decision, attr)
            self._determinism_tracker.validate_action(decision_attributes)

        self._add_state_machine(CompletionStateMachine(decision))

    def _next_id(self) -> str:
        next_id = self._id_counter
        self._id_counter += 1
        return str(next_id)

    def _get_machine(self, decision_id: DecisionId) -> DecisionStateMachine:
        machine = self.state_machines.get(decision_id, None)
        if machine is None:
            raise ValueError(f"Unknown state machine: {decision_id}")
        return machine

    def _add_state_machine(self, state: DecisionStateMachine) -> None:
        decision_id = state.get_id()
        if decision_id in self.state_machines:
            raise ValueError(f"Received duplicate decision: {decision_id}")
        self.state_machines[decision_id] = state
        self.aliases[(decision_id.decision_type, decision_id.id)] = state

    # ----- History routing -----

    def handle_history_event(self, event: history.HistoryEvent) -> None:
        """Dispatch history event to typed handlers using the global transition map."""
        attr = event.WhichOneof("attributes")
        event_attributes = getattr(event, attr)

        # Based on the type of the event, determine what DecisionType it's referencing and
        # the correct action to take
        event_action = DecisionManager.type_to_action.get(
            event_attributes.__class__, None
        )
        if event_action is not None:
            decision_type = event_action.decision_type
            action = event_action.action
            if decision_type is DecisionType.MARKER:
                self._index_marker_details(event_attributes)
                machine = self._state_machine_for_marker_event(event_attributes)
                if machine is None:
                    return
            else:
                machine = self._state_machine_for_event(
                    event.event_id, decision_type, action, event_attributes
                )

            action.fn(machine, event_attributes)

            # Certain events (scheduled) are often referenced by subsequent events
            # rather than using the client provided id
            if action.event_id_is_alias:
                self.aliases[(decision_type, event.event_id)] = machine

    def _state_machine_for_event(
        self,
        event_id: int,
        decision_type: DecisionType,
        action: Action,
        event_attributes: object,
    ) -> DecisionStateMachine:
        # This may resolve via a user id, an event-id alias, or a nested proto field
        # such as workflow_execution.workflow_id.
        id_for_event = resolve_id_attr(event_attributes, action.id_attr)
        alias = (decision_type, id_for_event)
        machine = self.aliases.get(alias, None)
        if machine is None:
            raise KeyError(f"Event {event_id} references unknown state machine {alias}")
        return machine

    def _state_machine_for_marker_event(
        self,
        event_attributes: history.MarkerRecordedEventAttributes,
    ) -> DecisionStateMachine | None:
        # Immediate-cancellation markers are matched by DeterminismTracker, not routed
        # through a MarkerStateMachine — handle them explicitly rather than via decode-failure below.
        if is_immediate_cancel(event_attributes):
            logger.debug(
                "Marker '%s' is the immediate-cancellation marker — handled by "
                "DeterminismTracker, not routed through a MarkerStateMachine",
                event_attributes.marker_name,
            )
            return None

        # Marker events are preloaded before workflow code runs. If no marker
        # decision has been requested yet, keep the preloaded event as a no-op.
        context_id = marker_context_id(event_attributes)
        if context_id is None:
            logger.debug(
                "Marker '%s' has no marker header — skipping routing "
                "(produced by another SDK or pre-header history)",
                event_attributes.marker_name,
            )
            return None
        marker_id = marker_decision_id(event_attributes.marker_name, context_id)
        machine = self.aliases.get((marker_id.decision_type, marker_id.id), None)
        if machine is None:
            if event_attributes.marker_name not in KNOWN_MARKER_NAMES:
                logger.warning(
                    "Marker event with unknown marker_name '%s' (key='%s') has no "
                    "matching state machine and will be dropped",
                    event_attributes.marker_name,
                    marker_id.id,
                )
            else:
                logger.debug(
                    "No state machine for marker '%s' yet (key='%s') — "
                    "marker is preloaded before workflow code runs",
                    event_attributes.marker_name,
                    marker_id.id,
                )
        return machine

    def _index_marker_details(
        self, attrs: history.MarkerRecordedEventAttributes
    ) -> None:
        """Store the user payload from a recorded marker event, keyed by its marker DecisionId.

        Called for every MarkerRecordedEvent (both during preload and output replay) so
        that record_marker can return the historical value on replay without routing
        through Expectation.properties.
        """
        if is_immediate_cancel(attrs):
            return
        context_id = marker_context_id(attrs)
        if context_id is None:
            return
        marker_id = marker_decision_id(attrs.marker_name, context_id)
        self._recorded_marker_details[marker_id] = Payload(data=attrs.details.data)

    # ---- Non-determinism ----
    @contextmanager
    def track_nondeterminism(
        self, replaying: bool, outcomes: List[history.HistoryEvent]
    ) -> Iterator[None]:
        self._start_execution(replaying, outcomes)
        yield
        self._end_execution()

    def _start_execution(self, replaying: bool, outcomes: List[history.HistoryEvent]):
        self._replaying = replaying
        for event in outcomes:
            self._determinism_tracker.add_expectation(event)
            if event.HasField("marker_recorded_event_attributes"):
                self._index_marker_details(event.marker_recorded_event_attributes)

    def _end_execution(self) -> None:
        if self._replaying:
            self._determinism_tracker.complete_replay()
        self._replaying = False

    # ----- Decision aggregation -----

    def collect_pending_decisions(self) -> List[decision.Decision]:
        completion_machine = self.state_machines.get(COMPLETION_ID)
        completion_decision = (
            completion_machine.get_decision() if completion_machine else None
        )
        is_completing = completion_decision is not None

        decisions: List[decision.Decision] = []
        for decision_id, machine in self.state_machines.items():
            if decision_id == COMPLETION_ID:
                continue
            d = machine.get_decision()
            if d is not None:
                decisions.append(d)

        if is_completing:
            assert completion_decision is not None  # same predicate as is_completing
            decisions.append(completion_decision)

        return decisions

    def _create_future(self, decision_id: DecisionId) -> DecisionFuture[T]:
        return DecisionFuture[T](
            self._event_loop,
            self._create_cancel_callback(decision_id),
        )

    def _create_cancel_callback(self, decision_id: DecisionId) -> CancelFn:
        def request_cancel(message: str | None = None) -> bool:
            return self._request_cancel(decision_id, message)

        return request_cancel

    def _request_cancel(
        self, decision_id: DecisionId, message: str | None = None
    ) -> bool:
        machine = self._get_machine(decision_id)
        if machine.request_cancel(message):
            if self._replaying:
                self._determinism_tracker.validate_cancel(decision_id)
            # Interactions with the state machines should move them to the end so that the decisions are ordered as they
            # happened in the Workflow
            self.state_machines.move_to_end(decision_id)
            return True
        return False
