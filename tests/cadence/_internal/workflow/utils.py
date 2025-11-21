from typing import List
from cadence.api.v1.history_pb2 import HistoryEvent


def create_mock_history_event(event_types: List[str]) -> List[HistoryEvent]:
    events = []
    for i, event_type in enumerate(event_types):
        event = HistoryEvent()
        event.event_id = i + 1
        event.event_time.FromMilliseconds((i + 1) * 1000)

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
