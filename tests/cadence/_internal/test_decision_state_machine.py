import pytest

from cadence.api.v1 import (
    decision_pb2 as decision,
    history_pb2 as history,
    common_pb2 as common,
)

from cadence._internal.decision_state_machine import (
    ActivityDecisionMachine,
    TimerDecisionMachine,
    ChildWorkflowDecisionMachine,
    DecisionManager,
    DecisionState,
)


@pytest.mark.unit
def test_timer_state_machine_cancel_before_sent():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t-cbs")
    m = TimerDecisionMachine(timer_id="t-cbs", start_attributes=attrs)
    m.request_cancel()
    d = m.collect_pending_decisions()
    assert len(d) == 2
    assert d[0].HasField("start_timer_decision_attributes")
    assert d[1].HasField("cancel_timer_decision_attributes")


@pytest.mark.unit
def test_timer_state_machine_cancel_after_initiated():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t-cai")
    m = TimerDecisionMachine(timer_id="t-cai", start_attributes=attrs)
    _ = m.collect_pending_decisions()
    m.handle_initiated_event(
        history.HistoryEvent(
            event_id=1,
            timer_started_event_attributes=history.TimerStartedEventAttributes(
                timer_id="t-cai"
            ),
        )
    )
    m.request_cancel()
    d = m.collect_pending_decisions()
    assert len(d) == 1 and d[0].HasField("cancel_timer_decision_attributes")


@pytest.mark.unit
def test_timer_state_machine_completed_after_cancel():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t-cac")
    m = TimerDecisionMachine(timer_id="t-cac", start_attributes=attrs)
    _ = m.collect_pending_decisions()
    m.handle_initiated_event(
        history.HistoryEvent(
            event_id=2,
            timer_started_event_attributes=history.TimerStartedEventAttributes(
                timer_id="t-cac"
            ),
        )
    )
    m.request_cancel()
    _ = m.collect_pending_decisions()
    m.handle_completion_event(
        history.HistoryEvent(
            event_id=3,
            timer_fired_event_attributes=history.TimerFiredEventAttributes(
                timer_id="t-cac", started_event_id=2
            ),
        )
    )
    assert m.status is DecisionState.COMPLETED


@pytest.mark.unit
def test_timer_state_machine_complete_without_cancel():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t-cwc")
    m = TimerDecisionMachine(timer_id="t-cwc", start_attributes=attrs)
    _ = m.collect_pending_decisions()
    m.handle_initiated_event(
        history.HistoryEvent(
            event_id=4,
            timer_started_event_attributes=history.TimerStartedEventAttributes(
                timer_id="t-cwc"
            ),
        )
    )
    m.handle_completion_event(
        history.HistoryEvent(
            event_id=5,
            timer_fired_event_attributes=history.TimerFiredEventAttributes(
                timer_id="t-cwc", started_event_id=4
            ),
        )
    )
    assert m.status is DecisionState.COMPLETED


@pytest.mark.unit
@pytest.mark.skip(
    "Invalid state transition panics are not applicable in this Python implementation"
)
def test_timer_state_machine_panic_invalid_state_transition():
    pass


@pytest.mark.unit
def test_timer_cancel_event_ordering():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t-ord")
    m = TimerDecisionMachine(timer_id="t-ord", start_attributes=attrs)
    _ = m.collect_pending_decisions()
    m.handle_initiated_event(
        history.HistoryEvent(
            event_id=10,
            timer_started_event_attributes=history.TimerStartedEventAttributes(
                timer_id="t-ord"
            ),
        )
    )
    m.request_cancel()
    d1 = m.collect_pending_decisions()
    assert len(d1) == 1 and d1[0].HasField("cancel_timer_decision_attributes")
    # Simulate cancel failed -> should retry emit
    m.handle_cancel_failed_event(
        history.HistoryEvent(
            event_id=11,
            cancel_timer_failed_event_attributes=history.CancelTimerFailedEventAttributes(
                timer_id="t-ord"
            ),
        )
    )
    d2 = m.collect_pending_decisions()
    assert len(d2) == 1 and d2[0].HasField("cancel_timer_decision_attributes")


@pytest.mark.unit
def test_activity_state_machine_complete_without_cancel():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="act-1")
    m = ActivityDecisionMachine(activity_id="act-1", schedule_attributes=attrs)
    d = m.collect_pending_decisions()
    assert len(d) == 1 and d[0].HasField("schedule_activity_task_decision_attributes")
    m.handle_initiated_event(
        history.HistoryEvent(
            event_id=20,
            activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                activity_id="act-1"
            ),
        )
    )
    m.handle_started_event(
        history.HistoryEvent(
            event_id=21,
            activity_task_started_event_attributes=history.ActivityTaskStartedEventAttributes(
                scheduled_event_id=20
            ),
        )
    )
    m.handle_completion_event(
        history.HistoryEvent(
            event_id=22,
            activity_task_completed_event_attributes=history.ActivityTaskCompletedEventAttributes(
                scheduled_event_id=20, started_event_id=21
            ),
        )
    )
    assert m.status is DecisionState.COMPLETED


@pytest.mark.unit
def test_activity_state_machine_cancel_before_sent():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="act-cbs")
    m = ActivityDecisionMachine(activity_id="act-cbs", schedule_attributes=attrs)
    m.request_cancel()
    d = m.collect_pending_decisions()
    # Should emit schedule then cancel
    assert len(d) == 2
    assert d[0].HasField("schedule_activity_task_decision_attributes")
    assert d[1].HasField("request_cancel_activity_task_decision_attributes")


@pytest.mark.unit
def test_activity_state_machine_cancel_after_sent():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="act-cas")
    m = ActivityDecisionMachine(activity_id="act-cas", schedule_attributes=attrs)
    _ = m.collect_pending_decisions()
    m.request_cancel()
    d = m.collect_pending_decisions()
    assert len(d) == 1 and d[0].HasField(
        "request_cancel_activity_task_decision_attributes"
    )


@pytest.mark.unit
def test_activity_state_machine_completed_after_cancel():
    attrs = decision.ScheduleActivityTaskDecisionAttributes(activity_id="act-cac")
    m = ActivityDecisionMachine(activity_id="act-cac", schedule_attributes=attrs)
    _ = m.collect_pending_decisions()
    m.handle_initiated_event(
        history.HistoryEvent(
            event_id=30,
            activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                activity_id="act-cac"
            ),
        )
    )
    m.handle_started_event(
        history.HistoryEvent(
            event_id=31,
            activity_task_started_event_attributes=history.ActivityTaskStartedEventAttributes(
                scheduled_event_id=30
            ),
        )
    )
    m.request_cancel()
    _ = m.collect_pending_decisions()
    m.handle_completion_event(
        history.HistoryEvent(
            event_id=32,
            activity_task_completed_event_attributes=history.ActivityTaskCompletedEventAttributes(
                scheduled_event_id=30, started_event_id=31
            ),
        )
    )
    assert m.status is DecisionState.COMPLETED


@pytest.mark.unit
@pytest.mark.skip(
    "Invalid state transition panics are not applicable in this Python implementation"
)
def test_activity_state_machine_panic_invalid_state_transition():
    pass


@pytest.mark.unit
def test_child_workflow_state_machine_basic():
    attrs = decision.StartChildWorkflowExecutionDecisionAttributes(
        domain="d1", workflow_id="wf-1", workflow_type=common.WorkflowType(name="t")
    )
    m = ChildWorkflowDecisionMachine(client_id="cw-1", start_attributes=attrs)
    d = m.collect_pending_decisions()
    assert len(d) == 1 and d[0].HasField(
        "start_child_workflow_execution_decision_attributes"
    )
    m.handle_initiated_event(
        history.HistoryEvent(
            event_id=40,
            start_child_workflow_execution_initiated_event_attributes=history.StartChildWorkflowExecutionInitiatedEventAttributes(
                domain="d1", workflow_id="wf-1"
            ),
        )
    )
    m.handle_started_event(
        history.HistoryEvent(
            event_id=41,
            child_workflow_execution_started_event_attributes=history.ChildWorkflowExecutionStartedEventAttributes(
                initiated_event_id=40
            ),
        )
    )
    m.handle_completion_event(
        history.HistoryEvent(
            event_id=42,
            child_workflow_execution_completed_event_attributes=history.ChildWorkflowExecutionCompletedEventAttributes(
                initiated_event_id=40
            ),
        )
    )
    assert m.status is DecisionState.COMPLETED


@pytest.mark.unit
def test_child_workflow_state_machine_cancel_succeed():
    attrs = decision.StartChildWorkflowExecutionDecisionAttributes(
        domain="d2", workflow_id="wf-2", workflow_type=common.WorkflowType(name="t2")
    )
    m = ChildWorkflowDecisionMachine(client_id="cw-2", start_attributes=attrs)
    _ = m.collect_pending_decisions()
    m.handle_initiated_event(
        history.HistoryEvent(
            event_id=50,
            start_child_workflow_execution_initiated_event_attributes=history.StartChildWorkflowExecutionInitiatedEventAttributes(
                domain="d2", workflow_id="wf-2"
            ),
        )
    )
    m.request_cancel()
    d = m.collect_pending_decisions()
    assert len(d) == 1 and d[0].HasField(
        "request_cancel_external_workflow_execution_decision_attributes"
    )
    m.handle_canceled_event(
        history.HistoryEvent(
            event_id=51,
            child_workflow_execution_canceled_event_attributes=history.ChildWorkflowExecutionCanceledEventAttributes(
                initiated_event_id=50
            ),
        )
    )
    assert m.status is DecisionState.CANCELED


@pytest.mark.unit
@pytest.mark.skip("Invalid state checks from Go are not applicable here")
def test_child_workflow_state_machine_invalid_states():
    pass


@pytest.mark.unit
@pytest.mark.skip("External cancel failure event handling is not implemented")
def test_child_workflow_state_machine_cancel_failed():
    pass


@pytest.mark.unit
@pytest.mark.skip("Marker decision state machine is not implemented in this module")
def test_marker_state_machine():
    pass


@pytest.mark.unit
@pytest.mark.skip(
    "Upsert search attributes decision state machine is not implemented in this module"
)
def test_upsert_search_attributes_decision_state_machine():
    pass


@pytest.mark.unit
@pytest.mark.skip(
    "Cancel external workflow decision state machine is not implemented in this module"
)
def test_cancel_external_workflow_state_machine_succeed():
    pass


@pytest.mark.unit
@pytest.mark.skip(
    "Cancel external workflow decision state machine is not implemented in this module"
)
def test_cancel_external_workflow_state_machine_failed():
    pass


@pytest.mark.unit
def test_manager_aggregates_and_routes():
    dm = DecisionManager()

    # Create three machines via public API
    a = dm.schedule_activity(
        "a1", decision.ScheduleActivityTaskDecisionAttributes(activity_id="a1")
    )
    t = dm.start_timer("t1", decision.StartTimerDecisionAttributes(timer_id="t1"))
    c = dm.start_child_workflow(
        "c1",
        decision.StartChildWorkflowExecutionDecisionAttributes(
            domain="d", workflow_id="w1", workflow_type=common.WorkflowType(name="t")
        ),
    )

    # First collect should include 3 decisions (schedule/start/start_child)
    decisions_first = dm.collect_pending_decisions()
    assert len(decisions_first) == 3

    # Idempotent on second collect
    assert dm.collect_pending_decisions() == []

    # Route initiated events
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=100,
            activity_task_scheduled_event_attributes=history.ActivityTaskScheduledEventAttributes(
                activity_id="a1"
            ),
        )
    )
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=101,
            timer_started_event_attributes=history.TimerStartedEventAttributes(
                timer_id="t1"
            ),
        )
    )
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=102,
            start_child_workflow_execution_initiated_event_attributes=history.StartChildWorkflowExecutionInitiatedEventAttributes(
                domain="d", workflow_id="w1"
            ),
        )
    )

    assert a.status is DecisionState.INITIATED
    assert t.status is DecisionState.INITIATED
    assert c.status is DecisionState.INITIATED

    # Route started and completion events
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=103,
            activity_task_started_event_attributes=history.ActivityTaskStartedEventAttributes(
                scheduled_event_id=100
            ),
        )
    )
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=104,
            child_workflow_execution_started_event_attributes=history.ChildWorkflowExecutionStartedEventAttributes(
                initiated_event_id=102
            ),
        )
    )
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=105,
            activity_task_completed_event_attributes=history.ActivityTaskCompletedEventAttributes(
                scheduled_event_id=100, started_event_id=103
            ),
        )
    )
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=106,
            timer_fired_event_attributes=history.TimerFiredEventAttributes(
                timer_id="t1", started_event_id=101
            ),
        )
    )
    dm.handle_history_event(
        history.HistoryEvent(
            event_id=107,
            child_workflow_execution_completed_event_attributes=history.ChildWorkflowExecutionCompletedEventAttributes(
                initiated_event_id=102
            ),
        )
    )

    assert a.status is DecisionState.COMPLETED
    assert t.status is DecisionState.COMPLETED
    assert c.status is DecisionState.COMPLETED
