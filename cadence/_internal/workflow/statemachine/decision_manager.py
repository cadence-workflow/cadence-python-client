import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Type, Tuple, ClassVar, List

from cadence._internal.workflow.statemachine.activity_state_machine import (
    activity_events,
    ActivityStateMachine,
)
from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionId,
    DecisionStateMachine,
    DecisionType,
    DecisionFuture,
    T,
)
from cadence._internal.workflow.statemachine.event_dispatcher import (
    EventDispatcher,
    Action,
)
from cadence._internal.workflow.statemachine.timer_state_machine import (
    TimerStateMachine,
    timer_events,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Payload

DecisionAlias = Tuple[DecisionType, str | int]


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
        }
    )

    def __init__(self, event_loop: asyncio.AbstractEventLoop):
        self._event_loop = event_loop
        self.state_machines: OrderedDict[DecisionId, DecisionStateMachine] = (
            OrderedDict()
        )
        self.aliases: Dict[DecisionAlias, DecisionStateMachine] = dict()

    # ----- Activity API -----

    def schedule_activity(
        self, attrs: decision.ScheduleActivityTaskDecisionAttributes
    ) -> asyncio.Future[Payload]:
        decision_id = DecisionId(DecisionType.ACTIVITY, attrs.activity_id)
        future: DecisionFuture[Payload] = self._create_future(decision_id)
        machine = ActivityStateMachine(attrs, future)
        self._add_state_machine(machine)

        return future

    # ----- Timer API -----

    def start_timer(
        self, attrs: decision.StartTimerDecisionAttributes
    ) -> asyncio.Future[None]:
        decision_id = DecisionId(DecisionType.TIMER, attrs.timer_id)
        future: DecisionFuture[None] = self._create_future(decision_id)
        machine = TimerStateMachine(attrs, future)
        self._add_state_machine(machine)

        return future

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
        # Based on the type of the event, determine what DecisionType it's referencing and
        # the correct action to take
        event_attributes = getattr(event, attr)
        event_action = DecisionManager.type_to_action.get(
            event_attributes.__class__, None
        )
        if event_action is not None:
            decision_type = event_action.decision_type
            action = event_action.action
            # Find what state machine the event references.
            # This may be a reference via the user id or a reference to a previous event
            id_for_event = getattr(event_attributes, action.id_attr)
            alias = (decision_type, id_for_event)
            machine = self.aliases.get(alias, None)
            if machine is None:
                raise KeyError(
                    f"Event {event.event_id} references unknown state machine {alias}"
                )

            action.fn(machine, event_attributes)

            # Certain events (scheduled) are often referenced by subsequent events
            # rather than using the client provided id
            if action.event_id_is_alias:
                self.aliases[(decision_type, event.event_id)] = machine

    # ----- Decision aggregation -----

    def collect_pending_decisions(self) -> List[decision.Decision]:
        decisions: List[decision.Decision] = []

        for machine in self.state_machines.values():
            to_send = machine.get_decision()
            if to_send is not None:
                decisions.append(to_send)

        return decisions

    def _create_future(self, decision_id: DecisionId) -> DecisionFuture[T]:
        return DecisionFuture[T](
            self._event_loop, lambda: self._request_cancel(decision_id)
        )

    def _request_cancel(self, decision_id: DecisionId) -> bool:
        machine = self._get_machine(decision_id)
        # Interactions with the state machines should move them to the end so that the decisions are ordered as they
        # happened in the Workflow
        self.state_machines.move_to_end(decision_id)
        return machine.request_cancel()
