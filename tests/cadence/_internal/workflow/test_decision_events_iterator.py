#!/usr/bin/env python3
"""
Tests for Decision Events Iterator.
"""

import pytest


from cadence._internal.workflow.decision_events_iterator import (
    DecisionEventsIterator,
)
from tests.cadence._internal.workflow.utils import create_mock_history_event


class TestDecisionEventsIterator:
    """Test the DecisionEventsIterator class."""

    @pytest.mark.parametrize(
        "name, event_types, expected",
        [
            (
                "workflow_started",
                [
                    "workflow_execution_started",
                    "decision_task_scheduled",
                    "decision_task_started",
                ],
                [
                    {
                        "input": 2,
                        "output": 0,
                        "markers": 0,
                        "replay": False,
                        "replay_time": 3000,
                        "next_decision_event_id": 5,
                    },
                ],
            ),
            (
                "workflow_with_activity_scheduled",
                [
                    "workflow_execution_started",
                    "decision_task_scheduled",
                    "decision_task_started",
                    "decision_task_completed",
                    "activity_scheduled",
                ],
                [
                    {
                        "input": 2,
                        "output": 1,
                        "markers": 0,
                        "replay": True,
                        "replay_time": 4000,
                        "next_decision_event_id": 5,
                    },
                ],
            ),
            (
                "workflow_with_activity_completed",
                [
                    "workflow_execution_started",
                    "decision_task_scheduled",
                    "decision_task_started",
                    "decision_task_completed",
                    "activity_scheduled",
                    "activity_started",
                    "activity_completed",
                    "decision_task_scheduled",
                    "decision_task_started",
                ],
                [
                    {
                        "input": 2,
                        "output": 1,
                        "markers": 0,
                        "replay": True,
                        "replay_time": 4000,
                        "next_decision_event_id": 5,
                    },
                    {
                        "input": 3,
                        "output": 0,
                        "markers": 0,
                        "replay": False,
                        "replay_time": 9000,
                        "next_decision_event_id": 11,
                    },
                ],
            ),
        ],
    )
    def test_successful_cases(self, name, event_types, expected):
        events = create_mock_history_event(event_types)
        iterator = DecisionEventsIterator(events)

        batches = [decision_events for decision_events in iterator]
        assert len(expected) == len(batches)

        for expect, batch in zip(expected, batches):
            assert len(batch.input) == expect["input"]
            assert len(batch.output) == expect["output"]
            assert len(batch.markers) == expect["markers"]
            assert batch.replay == expect["replay"]
            assert batch.replay_current_time_milliseconds == expect["replay_time"]
            assert batch.next_decision_event_id == expect["next_decision_event_id"]
