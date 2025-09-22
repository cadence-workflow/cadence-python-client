"""
HistoryHelper manages the addition of workflow history when a decision task is responded.

This helper ensures that the workflow history is properly tracked and updated
when decisions are made and responses are sent back to the Cadence service.
"""

import logging
from typing import List, Optional

from cadence.api.v1.decision_pb2 import Decision
from cadence.api.v1.history_pb2 import History, HistoryEvent

logger = logging.getLogger(__name__)


class HistoryHelper:
    """
    Helper class to manage workflow history updates when decisions are responded.

    This class tracks the current history state and adds new events as decisions
    are processed and responses are generated.
    """

    def __init__(self, initial_history: Optional[History] = None):
        """
        Initialize the HistoryHelper with optional initial history.

        Args:
            initial_history: The initial workflow history to start with
        """
        self._current_history = initial_history or History()
        self._next_event_id = self._calculate_next_event_id()
        logger.debug(
            f"HistoryHelper initialized with {len(self._current_history.events)} events, next event ID: {self._next_event_id}"
        )

    def _calculate_next_event_id(self) -> int:
        """
        Calculate the next event ID based on the current history.

        Returns:
            The next event ID to use for new events
        """
        if not self._current_history.events:
            return 1

        # Find the highest event ID in the current history
        max_event_id = max(
            event.event_id for event in self._current_history.events if event.event_id
        )
        return max_event_id + 1

    def get_current_history(self) -> History:
        """
        Get the current workflow history.

        Returns:
            The current History object
        """
        return self._current_history

    def get_event_count(self) -> int:
        """
        Get the current number of events in the history.

        Returns:
            The number of events in the current history
        """
        return len(self._current_history.events)

    def get_next_event_id(self) -> int:
        """
        Get the next event ID that would be assigned to a new event.

        Returns:
            The next event ID
        """
        return self._next_event_id

    def add_decision_task_started_event(
        self, task_token: bytes, identity: str
    ) -> HistoryEvent:
        """
        Add a DecisionTaskStarted event to the history.

        Args:
            task_token: The decision task token
            identity: The worker identity

        Returns:
            The created HistoryEvent
        """
        event = HistoryEvent()
        event.event_id = self._next_event_id
        event.decision_task_started_event_attributes.identity = identity
        # Note: task_token would typically be stored in the decision task context

        self._current_history.events.append(event)
        self._next_event_id += 1

        logger.debug(f"Added DecisionTaskStarted event with ID {event.event_id}")
        return event

    def add_decision_task_completed_event(
        self, decisions: List[Decision], execution_context: bytes = b""
    ) -> HistoryEvent:
        """
        Add a DecisionTaskCompleted event to the history.

        Args:
            decisions: The list of decisions that were made
            execution_context: Optional execution context

        Returns:
            The created HistoryEvent
        """
        event = HistoryEvent()
        event.event_id = self._next_event_id
        event.decision_task_completed_event_attributes.execution_context = (
            execution_context
        )
        # Note: decisions would be processed and their effects would generate subsequent events

        self._current_history.events.append(event)
        self._next_event_id += 1

        logger.debug(
            f"Added DecisionTaskCompleted event with ID {event.event_id} for {len(decisions)} decisions"
        )
        return event

    def add_decision_task_failed_event(
        self, cause: str, details: str = ""
    ) -> HistoryEvent:
        """
        Add a DecisionTaskFailed event to the history.

        Args:
            cause: The cause of the failure
            details: Additional failure details

        Returns:
            The created HistoryEvent
        """
        event = HistoryEvent()
        event.event_id = self._next_event_id
        event.decision_task_failed_event_attributes.cause = cause
        event.decision_task_failed_event_attributes.details = details

        self._current_history.events.append(event)
        self._next_event_id += 1

        logger.debug(
            f"Added DecisionTaskFailed event with ID {event.event_id}, cause: {cause}"
        )
        return event

    def update_from_new_history(self, new_history: History) -> None:
        """
        Update the current history with new events from a received history.

        This is typically called when a new decision task is received with
        updated history that includes events that happened since the last task.

        Args:
            new_history: The new history received from the service
        """
        if not new_history or not new_history.events:
            logger.debug("No new history events to process")
            return

        # Find events that are newer than our current history
        current_max_event_id = 0
        if self._current_history.events:
            current_max_event_id = max(
                event.event_id
                for event in self._current_history.events
                if event.event_id
            )

        new_events = [
            event
            for event in new_history.events
            if event.event_id > current_max_event_id
        ]

        if new_events:
            self._current_history.events.extend(new_events)
            self._next_event_id = self._calculate_next_event_id()
            logger.debug(
                f"Added {len(new_events)} new events, next event ID: {self._next_event_id}"
            )
        else:
            logger.debug("No new events found in the provided history")

    def reset_to_history(self, history: History) -> None:
        """
        Reset the current history to the provided history.

        This completely replaces the current history state.

        Args:
            history: The new history to use
        """
        self._current_history = history or History()
        self._next_event_id = self._calculate_next_event_id()
        logger.debug(
            f"History reset to {len(self._current_history.events)} events, next event ID: {self._next_event_id}"
        )

    def find_event_by_id(self, event_id: int) -> Optional[HistoryEvent]:
        """
        Find a specific event by its ID.

        Args:
            event_id: The event ID to search for

        Returns:
            The HistoryEvent if found, None otherwise
        """
        for event in self._current_history.events:
            if event.event_id == event_id:
                return event
        return None

    def get_events_since(self, event_id: int) -> List[HistoryEvent]:
        """
        Get all events that occurred after the specified event ID.

        Args:
            event_id: The event ID to search from

        Returns:
            List of HistoryEvents that occurred after the specified ID
        """
        return [
            event for event in self._current_history.events if event.event_id > event_id
        ]
