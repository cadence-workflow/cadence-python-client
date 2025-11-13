#!/usr/bin/env python3
"""
Tests for Decision Events Iterator.
"""

import pytest
from typing import List

from cadence.api.v1.history_pb2 import HistoryEvent, History, WorkflowExecutionStartedEventAttributes
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.api.v1.common_pb2 import WorkflowExecution
from google.protobuf.timestamp_pb2 import Timestamp

from cadence._internal.workflow.decision_events_iterator import (
    DecisionEventsIterator,
)

class TestDecisionEventsIterator:
    """Test the DecisionEventsIterator class."""


    @pytest.mark.parametrize(
        "name, event_types, expected",
        [
            (
                "workflow_started",
                ["workflow_execution_started", "decision_task_scheduled", "decision_task_started"],
                [
                    {
                        "input": 2,
                        "output": 0,
                        "markers": 0,
                        "replay": False,
                        "replay_time": 3000,
                        "next_decision_event_id": 5,
                    },
                ]
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
                ]
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
                ]
            )
        ],
    )
    def test_successful_cases(self, name, event_types, expected):
        events = create_mock_history_event(event_types)
        decision_task = create_mock_decision_task(events)
        iterator = DecisionEventsIterator(decision_task, events)

        batches = [decision_events for decision_events in iterator]
        assert len(expected) == len(batches)

        for expect, batch in zip(expected, batches):
            assert len(batch.input) == expect["input"]
            assert len(batch.output) == expect["output"]
            assert len(batch.markers) == expect["markers"]
            assert batch.replay == expect["replay"]
            assert batch.replay_current_time_milliseconds == expect["replay_time"]
            assert batch.next_decision_event_id == expect["next_decision_event_id"]

def create_mock_history_event(
    event_types: List[str]
) -> List[HistoryEvent]:

    events = []
    for i, event_type in enumerate(event_types):
        event = HistoryEvent()
        event.event_id = i + 1
        event.event_time.FromMilliseconds((i+1) * 1000)

        # Set the appropriate attribute based on event type
        if event_type == "decision_task_started":
            event.decision_task_started_event_attributes.SetInParent()
        elif event_type == "decision_task_completed":
            event.decision_task_completed_event_attributes.SetInParent()
        elif event_type == "decision_task_failed":
            event.decision_task_failed_event_attributes.SetInParent()
        elif event_type == "decision_task_timed_out":
            event.decision_task_timed_out_event_attributes.SetInParent()
        elif event_type == "marker_recorded":
            event.marker_recorded_event_attributes.SetInParent()
        elif event_type == "activity_scheduled":
            event.activity_task_scheduled_event_attributes.SetInParent()
        elif event_type == "activity_started":
            event.activity_task_started_event_attributes.SetInParent()
        elif event_type == "activity_completed":
            event.activity_task_completed_event_attributes.SetInParent()
        elif event_type == "activity_failed":
            event.activity_task_failed_event_attributes.SetInParent()
        elif event_type == "activity_timed_out":
            event.activity_task_timed_out_event_attributes.SetInParent()
        elif event_type == "activity_cancel_requested":
            event.activity_task_cancel_requested_event_attributes.SetInParent()
        elif event_type == "request_cancel_activity_task_failed":
            event.request_cancel_activity_task_failed_event_attributes.SetInParent()
        elif event_type == "activity_canceled":
            event.activity_task_canceled_event_attributes.SetInParent()
        elif event_type == "timer_started":
            event.timer_started_event_attributes.SetInParent()
        elif event_type == "timer_fired":
            event.timer_fired_event_attributes.SetInParent()
        elif event_type == "timer_canceled":
            event.timer_canceled_event_attributes.SetInParent()
        elif event_type == "cancel_timer_failed":
            event.cancel_timer_failed_event_attributes.SetInParent()
        elif event_type == "request_cancel_external_workflow_execution_initiated":
            event.request_cancel_external_workflow_execution_initiated_event_attributes.SetInParent()
        elif event_type == "request_cancel_external_workflow_execution_failed":
            event.request_cancel_external_workflow_execution_failed_event_attributes.SetInParent()
        elif event_type == "external_workflow_execution_cancel_requested":
            event.external_workflow_execution_cancel_requested_event_attributes.SetInParent()
        elif event_type == "workflow_execution_started":
            event.workflow_execution_started_event_attributes.SetInParent()
        elif event_type == "workflow_execution_completed":
            event.workflow_execution_completed_event_attributes.SetInParent()

        events.append(event)

    return events


def create_mock_decision_task(
    events: List[HistoryEvent], next_page_token: bytes = None
) -> PollForDecisionTaskResponse:
    """Create a mock decision task for testing."""
    task = PollForDecisionTaskResponse()

    # Mock history
    history = History()
    history.events.extend(events)
    task.history.CopyFrom(history)

    # Mock workflow execution
    workflow_execution = WorkflowExecution()
    workflow_execution.workflow_id = "test-workflow"
    workflow_execution.run_id = "test-run"
    task.workflow_execution.CopyFrom(workflow_execution)

    if next_page_token:
        task.next_page_token = next_page_token

    return task
