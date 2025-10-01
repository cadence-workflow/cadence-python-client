"""
DecisionsHelper manages the next decision ID which is used for tracking decision state machines.

This helper ensures that decision IDs are properly assigned and tracked to maintain
consistency in the workflow execution state.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from cadence._internal.decision_state_machine import DecisionId, DecisionType, DecisionManager

logger = logging.getLogger(__name__)


@dataclass
class DecisionTracker:
    """Tracks a decision with its ID and current state."""

    decision_id: DecisionId
    scheduled_event_id: Optional[int] = None
    initiated_event_id: Optional[int] = None
    started_event_id: Optional[int] = None
    is_completed: bool = False


class DecisionsHelper:
    """
    Helper class to manage decision IDs and work with DecisionManager state machines.

    This class generates unique decision IDs and integrates with the DecisionManager
    state machines for proper decision lifecycle tracking.
    """

    def __init__(self, decision_manager: DecisionManager):
        """
        Initialize the DecisionsHelper with a DecisionManager reference.

        Args:
            decision_manager: The DecisionManager containing the state machines
        """
        self._next_decision_counters: Dict[DecisionType, int] = {}
        self._tracked_decisions: Dict[str, DecisionTracker] = {}
        self._decision_id_to_key: Dict[str, str] = {}
        self._decision_manager = decision_manager
        logger.debug("DecisionsHelper initialized with DecisionManager integration")

    def _get_next_counter(self, decision_type: DecisionType) -> int:
        """
        Get the next counter value for a given decision type.

        Args:
            decision_type: The type of decision

        Returns:
            The next counter value
        """
        if decision_type not in self._next_decision_counters:
            self._next_decision_counters[decision_type] = 1
        else:
            self._next_decision_counters[decision_type] += 1

        return self._next_decision_counters[decision_type]

    def generate_activity_id(self, activity_name: str) -> str:
        """
        Generate a unique activity ID.

        Args:
            activity_name: The name of the activity

        Returns:
            A unique activity ID
        """
        counter = self._get_next_counter(DecisionType.ACTIVITY)
        activity_id = f"{activity_name}_{counter}"

        # Track this decision
        decision_id = DecisionId(DecisionType.ACTIVITY, activity_id)
        tracker = DecisionTracker(decision_id)
        self._tracked_decisions[activity_id] = tracker
        self._decision_id_to_key[str(decision_id)] = activity_id

        logger.debug(f"Generated activity ID: {activity_id}")
        return activity_id

    def generate_timer_id(self, timer_name: str = "timer") -> str:
        """
        Generate a unique timer ID.

        Args:
            timer_name: The name/prefix for the timer

        Returns:
            A unique timer ID
        """
        counter = self._get_next_counter(DecisionType.TIMER)
        timer_id = f"{timer_name}_{counter}"

        # Track this decision
        decision_id = DecisionId(DecisionType.TIMER, timer_id)
        tracker = DecisionTracker(decision_id)
        self._tracked_decisions[timer_id] = tracker
        self._decision_id_to_key[str(decision_id)] = timer_id

        logger.debug(f"Generated timer ID: {timer_id}")
        return timer_id

    def generate_child_workflow_id(self, workflow_name: str) -> str:
        """
        Generate a unique child workflow ID.

        Args:
            workflow_name: The name of the child workflow

        Returns:
            A unique child workflow ID
        """
        counter = self._get_next_counter(DecisionType.CHILD_WORKFLOW)
        workflow_id = f"{workflow_name}_{counter}"

        # Track this decision
        decision_id = DecisionId(DecisionType.CHILD_WORKFLOW, workflow_id)
        tracker = DecisionTracker(decision_id)
        self._tracked_decisions[workflow_id] = tracker
        self._decision_id_to_key[str(decision_id)] = workflow_id

        logger.debug(f"Generated child workflow ID: {workflow_id}")
        return workflow_id

    def generate_marker_id(self, marker_name: str) -> str:
        """
        Generate a unique marker ID.

        Args:
            marker_name: The name of the marker

        Returns:
            A unique marker ID
        """
        counter = self._get_next_counter(DecisionType.MARKER)
        marker_id = f"{marker_name}_{counter}"

        # Track this decision
        decision_id = DecisionId(DecisionType.MARKER, marker_id)
        tracker = DecisionTracker(decision_id)
        self._tracked_decisions[marker_id] = tracker
        self._decision_id_to_key[str(decision_id)] = marker_id

        logger.debug(f"Generated marker ID: {marker_id}")
        return marker_id

    def get_decision_tracker(self, decision_key: str) -> Optional[DecisionTracker]:
        """
        Get the decision tracker for a given decision key.

        Args:
            decision_key: The decision key (activity_id, timer_id, etc.)

        Returns:
            The DecisionTracker if found, None otherwise
        """
        return self._tracked_decisions.get(decision_key)

    def update_decision_scheduled(
        self, decision_key: str, scheduled_event_id: int
    ) -> None:
        """
        Update a decision tracker when it gets scheduled.

        Args:
            decision_key: The decision key
            scheduled_event_id: The event ID when the decision was scheduled
        """
        tracker = self._tracked_decisions.get(decision_key)
        if tracker:
            tracker.scheduled_event_id = scheduled_event_id
            logger.debug(
                f"Updated decision {decision_key} with scheduled event ID {scheduled_event_id}"
            )
        else:
            logger.warning(f"No tracker found for decision key: {decision_key}")

    def update_decision_initiated(
        self, decision_key: str, initiated_event_id: int
    ) -> None:
        """
        Update a decision tracker when it gets initiated.

        Args:
            decision_key: The decision key
            initiated_event_id: The event ID when the decision was initiated
        """
        tracker = self._tracked_decisions.get(decision_key)
        if tracker:
            tracker.initiated_event_id = initiated_event_id
            logger.debug(
                f"Updated decision {decision_key} with initiated event ID {initiated_event_id}"
            )
        else:
            logger.warning(f"No tracker found for decision key: {decision_key}")

    def update_decision_started(self, decision_key: str, started_event_id: int) -> None:
        """
        Update a decision tracker when it gets started.

        Args:
            decision_key: The decision key
            started_event_id: The event ID when the decision was started
        """
        tracker = self._tracked_decisions.get(decision_key)
        if tracker:
            tracker.started_event_id = started_event_id
            logger.debug(
                f"Updated decision {decision_key} with started event ID {started_event_id}"
            )
        else:
            logger.warning(f"No tracker found for decision key: {decision_key}")

    def update_decision_completed(self, decision_key: str) -> None:
        """
        Mark a decision as completed.

        Args:
            decision_key: The decision key
        """
        tracker = self._tracked_decisions.get(decision_key)
        if tracker:
            tracker.is_completed = True
            logger.debug(f"Marked decision {decision_key} as completed")
        else:
            logger.warning(f"No tracker found for decision key: {decision_key}")


    def _find_decision_by_scheduled_event_id(
        self, scheduled_event_id: int
    ) -> Optional[str]:
        """Find a decision key by its scheduled event ID."""
        for key, tracker in self._tracked_decisions.items():
            if tracker.scheduled_event_id == scheduled_event_id:
                return key
        return None

    def _find_decision_by_initiated_event_id(
        self, initiated_event_id: int
    ) -> Optional[str]:
        """Find a decision key by its initiated event ID."""
        for key, tracker in self._tracked_decisions.items():
            if tracker.initiated_event_id == initiated_event_id:
                return key
        return None

    def _find_decision_by_started_event_id(
        self, started_event_id: int
    ) -> Optional[str]:
        """Find a decision key by its started event ID."""
        for key, tracker in self._tracked_decisions.items():
            if tracker.started_event_id == started_event_id:
                return key
        return None

    def get_pending_decisions_count(self) -> int:
        """
        Get the count of decisions that are not yet completed.

        Returns:
            The number of pending decisions
        """
        return sum(
            1
            for tracker in self._tracked_decisions.values()
            if not tracker.is_completed
        )

    def get_completed_decisions_count(self) -> int:
        """
        Get the count of decisions that have been completed.

        Returns:
            The number of completed decisions
        """
        return sum(
            1 for tracker in self._tracked_decisions.values() if tracker.is_completed
        )

    def reset(self) -> None:
        """Reset all decision tracking state."""
        self._next_decision_counters.clear()
        self._tracked_decisions.clear()
        self._decision_id_to_key.clear()
        logger.debug("DecisionsHelper reset")

    def get_stats(self) -> Dict[str, int]:
        """
        Get statistics about tracked decisions.

        Returns:
            Dictionary with decision statistics
        """
        stats = {
            "total_decisions": len(self._tracked_decisions),
            "pending_decisions": self.get_pending_decisions_count(),
            "completed_decisions": self.get_completed_decisions_count(),
        }

        # Add per-type counts
        for decision_type in DecisionType:
            type_name = decision_type.name.lower()
            stats[f"{type_name}_count"] = self._next_decision_counters.get(
                decision_type, 0
            )

        return stats
