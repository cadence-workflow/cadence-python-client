#!/usr/bin/env python3
"""
Decision Events Iterator for Cadence workflow orchestration.

This module provides functionality to iterate through workflow history events,
particularly focusing on decision-related events for replay and execution.
"""

from dataclasses import dataclass
from typing import Iterator, List, Optional

from cadence._internal.workflow.history_event_iterator import HistoryEventsIterator
from cadence.api.v1.history_pb2 import HistoryEvent
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse


@dataclass
class DecisionEvents:
    """
    Represents events for a single decision iteration.
    """

    input: List[HistoryEvent]
    output: List[HistoryEvent]
    markers: List[HistoryEvent]
    replay: bool
    replay_current_time_milliseconds: int
    next_decision_event_id: int

    def get_output_event_by_id(self, event_id: int) -> Optional[HistoryEvent]:
        for event in self.input:
            if hasattr(event, "event_id") and event.event_id == event_id:
                return event
        return None


class DecisionEventsIterator(Iterator[DecisionEvents]):
    """
    Iterator for processing decision events from workflow history.

    This is the main class that processes workflow history events and groups them
    into decision iterations for proper workflow replay and execution.
    """

    def __init__(
        self,
        decision_task: PollForDecisionTaskResponse,
        events: List[HistoryEvent],
    ):
        self._decision_task = decision_task
        self._events: HistoryEventsIterator = HistoryEventsIterator(events)
        self._next_decision_event_id: Optional[int] = None
        self._replay_current_time_milliseconds: Optional[int] = None

    def __iter__(self):
        return self

    def __next__(self) -> DecisionEvents:
        """
        Process the next decision batch.
        1. Find the next valid decision task started event during replay or last scheduled decision task events for non-replay
        2. Collect the decision input events before the decision task
        3. Collect the decision output events after the decision task

        Relay mode is determined by checking if the decision task is completed or not
        """
        decision_input_events: List[HistoryEvent] = []
        decision_output_events: List[HistoryEvent] = []
        decision_event: Optional[HistoryEvent] = None
        for event in self._events:
            match event.WhichOneof("attributes"):
                case "decision_task_started_event_attributes":
                    next_event = self._events.peek()

                    # latest event, not replay, assign started event as decision event insteaad
                    if next_event is None:
                        decision_event = event
                        break

                    match next_event.WhichOneof("attributes"):
                        case (
                            "decision_task_failed_event_attributes"
                            | "decision_task_timed_out_event_attributes"
                        ):
                            # skip failed / timed out decision tasks and continue searching
                            next(self._events)
                            continue
                        case "decision_task_completed_event_attributes":
                            # found decision task completed event, stop
                            decision_event = next(self._events)
                            break
                        case _:
                            raise ValueError(
                                f"unexpected event type after decision task started event: {next_event}"
                            )

                case _:
                    decision_input_events.append(event)

        if not decision_event:
            raise StopIteration("no decision event found")

        # collect decision output events
        while self._events.has_next():
            nxt = self._events.peek() if self._events.has_next() else None
            if nxt and not is_decision_event(nxt):
                break
            decision_output_events.append(next(self._events))

        replay_current_time_milliseconds = decision_event.event_time.ToMilliseconds()

        replay: bool
        next_decision_event_id: int
        if (
            decision_event.WhichOneof("attributes")
            == "decision_task_completed_event_attributes"
        ):  # completed decision task
            replay = True
            next_decision_event_id = decision_event.event_id + 1
        else:
            replay = False
            next_decision_event_id = decision_event.event_id + 2

        # collect marker events
        markers = [m for m in decision_output_events if is_marker_event(m)]

        return DecisionEvents(
            input=decision_input_events,
            output=decision_output_events,
            markers=markers,
            replay=replay,
            replay_current_time_milliseconds=replay_current_time_milliseconds,
            next_decision_event_id=next_decision_event_id,
        )


def is_decision_event(event: HistoryEvent) -> bool:
    """Check if an event is a decision output event."""
    return event is not None and event.WhichOneof("attributes") in set(
        [
            "activity_task_scheduled_event_attributes",
            "start_child_workflow_execution_initiated_event_attributes",
            "timer_started_event_attributes",
            "workflow_execution_completed_event_attributes",
            "workflow_execution_failed_event_attributes",
            "workflow_execution_canceled_event_attributes",
            "workflow_execution_continued_as_new_event_attributes",
            "activity_task_cancel_requested_event_attributes",
            "request_cancel_activity_task_failed_event_attributes",
            "timer_canceled_event_attributes",
            "cancel_timer_failed_event_attributes",
            "request_cancel_external_workflow_execution_initiated_event_attributes",
            "marker_recorded_event_attributes",
            "signal_external_workflow_execution_initiated_event_attributes",
            "upsert_workflow_search_attributes_event_attributes",
        ]
    )


def is_marker_event(event: HistoryEvent) -> bool:
    return bool(
        event is not None
        and event.WhichOneof("attributes") == "marker_recorded_event_attributes"
    )
