#!/usr/bin/env python3
"""
Decision Events Iterator for Cadence workflow orchestration.

This module provides functionality to iterate through workflow history events,
particularly focusing on decision-related events for replay and execution.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from cadence.api.v1.history_pb2 import HistoryEvent
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.client import Client
from cadence._internal.workflow.history_event_iterator import iterate_history_events


@dataclass
class DecisionEvents:
    """
    Represents events for a single decision iteration.
    """

    events: List[HistoryEvent] = field(default_factory=list)
    markers: List[HistoryEvent] = field(default_factory=list)
    replay: bool = False
    replay_current_time_milliseconds: Optional[int] = None
    next_decision_event_id: Optional[int] = None

    def get_events(self) -> List[HistoryEvent]:
        """Return all events in this decision iteration."""
        return self.events

    def get_markers(self) -> List[HistoryEvent]:
        """Return marker events."""
        return self.markers

    def is_replay(self) -> bool:
        """Check if this decision is in replay mode."""
        return self.replay

    def get_event_by_id(self, event_id: int) -> Optional[HistoryEvent]:
        """Retrieve a specific event by ID, returns None if not found."""
        for event in self.events:
            if hasattr(event, "event_id") and event.event_id == event_id:
                return event
        return None


class DecisionEventsIterator:
    """
    Iterator for processing decision events from workflow history.

    This is the main class that processes workflow history events and groups them
    into decision iterations for proper workflow replay and execution.
    """

    def __init__(self, decision_task: PollForDecisionTaskResponse, client: Client):
        self._client = client
        self._decision_task = decision_task
        self._events: List[HistoryEvent] = []
        self._event_index = 0
        self._decision_task_started_event: Optional[HistoryEvent] = None
        self._next_decision_event_id = 1
        self._replay = True
        self._replay_current_time_milliseconds: Optional[int] = None
        self._initialized = False

    @staticmethod
    def _is_decision_task_started(event: HistoryEvent) -> bool:
        """Check if event is DecisionTaskStarted."""
        return hasattr(
            event, "decision_task_started_event_attributes"
        ) and event.HasField("decision_task_started_event_attributes")

    @staticmethod
    def _is_decision_task_completed(event: HistoryEvent) -> bool:
        """Check if event is DecisionTaskCompleted."""
        return hasattr(
            event, "decision_task_completed_event_attributes"
        ) and event.HasField("decision_task_completed_event_attributes")

    @staticmethod
    def _is_decision_task_failed(event: HistoryEvent) -> bool:
        """Check if event is DecisionTaskFailed."""
        return hasattr(
            event, "decision_task_failed_event_attributes"
        ) and event.HasField("decision_task_failed_event_attributes")

    @staticmethod
    def _is_decision_task_timed_out(event: HistoryEvent) -> bool:
        """Check if event is DecisionTaskTimedOut."""
        return hasattr(
            event, "decision_task_timed_out_event_attributes"
        ) and event.HasField("decision_task_timed_out_event_attributes")

    @staticmethod
    def _is_marker_recorded(event: HistoryEvent) -> bool:
        """Check if event is MarkerRecorded."""
        return hasattr(event, "marker_recorded_event_attributes") and event.HasField(
            "marker_recorded_event_attributes"
        )

    @staticmethod
    def _is_decision_task_completion(event: HistoryEvent) -> bool:
        """Check if event is any kind of decision task completion."""
        return (
            DecisionEventsIterator._is_decision_task_completed(event)
            or DecisionEventsIterator._is_decision_task_failed(event)
            or DecisionEventsIterator._is_decision_task_timed_out(event)
        )

    async def _ensure_initialized(self):
        """Initialize events list using the existing iterate_history_events."""
        if not self._initialized:
            # Use existing iterate_history_events function
            events_iterator = iterate_history_events(self._decision_task, self._client)
            self._events = [event async for event in events_iterator]
            self._initialized = True

            # Find first decision task started event
            for i, event in enumerate(self._events):
                if self._is_decision_task_started(event):
                    self._event_index = i
                    break

    async def has_next_decision_events(self) -> bool:
        """Check if there are more decision events to process."""
        await self._ensure_initialized()

        # Look for the next DecisionTaskStarted event from current position
        for i in range(self._event_index, len(self._events)):
            if self._is_decision_task_started(self._events[i]):
                return True

        return False

    async def next_decision_events(self) -> DecisionEvents:
        """
        Get the next set of decision events.

        This method processes events starting from a DecisionTaskStarted event
        until the corresponding DecisionTaskCompleted/Failed/TimedOut event.
        """
        await self._ensure_initialized()

        # Find next DecisionTaskStarted event
        start_index = None
        for i in range(self._event_index, len(self._events)):
            if self._is_decision_task_started(self._events[i]):
                start_index = i
                break

        if start_index is None:
            raise StopIteration("No more decision events")

        decision_events = DecisionEvents()
        decision_events.replay = self._replay
        decision_events.replay_current_time_milliseconds = (
            self._replay_current_time_milliseconds
        )
        decision_events.next_decision_event_id = self._next_decision_event_id

        # Process DecisionTaskStarted event
        decision_task_started = self._events[start_index]
        self._decision_task_started_event = decision_task_started
        decision_events.events.append(decision_task_started)

        # Update replay time if available
        if decision_task_started.event_time:
            self._replay_current_time_milliseconds = (
                decision_task_started.event_time.seconds * 1000
            )
            decision_events.replay_current_time_milliseconds = (
                self._replay_current_time_milliseconds
            )

        # Process subsequent events until we find the corresponding DecisionTask completion
        current_index = start_index + 1
        while current_index < len(self._events):
            event = self._events[current_index]
            decision_events.events.append(event)

            # Categorize the event
            if self._is_marker_recorded(event):
                decision_events.markers.append(event)
            elif self._is_decision_task_completion(event):
                # This marks the end of this decision iteration
                self._process_decision_completion_event(event, decision_events)
                current_index += 1  # Move past this event
                break

            current_index += 1

        # Update the event index for next iteration
        self._event_index = current_index

        # Update the next decision event ID
        if decision_events.events:
            last_event = decision_events.events[-1]
            if hasattr(last_event, "event_id"):
                self._next_decision_event_id = last_event.event_id + 1

        # Check if this is the last decision events
        # Set replay to false only if there are no more decision events after this one
        # Check directly without calling has_next_decision_events to avoid recursion
        has_more = False
        for i in range(self._event_index, len(self._events)):
            if self._is_decision_task_started(self._events[i]):
                has_more = True
                break

        if not has_more:
            self._replay = False
            decision_events.replay = False

        return decision_events

    def _process_decision_completion_event(
        self, event: HistoryEvent, decision_events: DecisionEvents
    ):
        """Process the decision completion event and update state."""

        # Check if we're still in replay mode
        # This is determined by comparing event IDs with the current decision task's started event ID
        if (
            self._decision_task_started_event
            and hasattr(self._decision_task_started_event, "event_id")
            and hasattr(event, "event_id")
        ):
            # If this completion event ID is >= the current decision task's started event ID,
            # we're no longer in replay mode
            current_task_started_id = (
                getattr(self._decision_task.started_event_id, "value", 0)
                if hasattr(self._decision_task, "started_event_id")
                else 0
            )

            if event.event_id >= current_task_started_id:
                self._replay = False
                decision_events.replay = False

    def get_replay_current_time_milliseconds(self) -> Optional[int]:
        """Get the current replay time in milliseconds."""
        return self._replay_current_time_milliseconds

    def is_replay_mode(self) -> bool:
        """Check if the iterator is currently in replay mode."""
        return self._replay

    def __aiter__(self):
        return self

    async def __anext__(self) -> DecisionEvents:
        if not await self.has_next_decision_events():
            raise StopAsyncIteration
        return await self.next_decision_events()


# Utility functions
def is_decision_event(event: HistoryEvent) -> bool:
    """Check if an event is a decision-related event."""
    return (
        DecisionEventsIterator._is_decision_task_started(event)
        or DecisionEventsIterator._is_decision_task_completed(event)
        or DecisionEventsIterator._is_decision_task_failed(event)
        or DecisionEventsIterator._is_decision_task_timed_out(event)
    )


def is_marker_event(event: HistoryEvent) -> bool:
    """Check if an event is a marker event."""
    return DecisionEventsIterator._is_marker_recorded(event)


def extract_event_timestamp_millis(event: HistoryEvent) -> Optional[int]:
    """Extract timestamp from an event in milliseconds."""
    if hasattr(event, "event_time") and event.HasField("event_time"):
        seconds = getattr(event.event_time, "seconds", 0)
        return seconds * 1000 if seconds > 0 else None
    return None
