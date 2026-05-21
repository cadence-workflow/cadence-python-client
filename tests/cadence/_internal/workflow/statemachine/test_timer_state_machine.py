from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionFuture,
)
from cadence._internal.workflow.statemachine.nondeterminism import (
    record_immediate_cancel,
)
from cadence._internal.workflow.statemachine.timer_state_machine import (
    TimerStateMachine,
)
from cadence.api.v1 import decision, history
from cadence.api.v1.decision_pb2 import CancelTimerDecisionAttributes


### These tests have to be async because they rely on the presence of an eventloop


async def test_timer_state_machine_started():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t-cbs")
    completed = DecisionFuture[None]()
    m = TimerStateMachine(attrs, completed)

    assert completed.done() is False
    assert m.get_decision() == decision.Decision(start_timer_decision_attributes=attrs)


async def test_timer_state_machine_cancel_before_sent():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t")
    completed = DecisionFuture[None]()
    m = TimerStateMachine(attrs, completed)

    assert m.request_cancel() is True

    assert completed.done() is True
    assert m.get_decision() == record_immediate_cancel(attrs)


async def test_timer_state_machine_cancel_after_initiated():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t")
    completed = DecisionFuture[None]()
    m = TimerStateMachine(attrs, completed)

    m.handle_started(history.TimerStartedEventAttributes(timer_id="t"))
    res = m.request_cancel()

    assert res is True
    assert completed.done() is True
    assert m.get_decision() == decision.Decision(
        cancel_timer_decision_attributes=CancelTimerDecisionAttributes(timer_id="t")
    )


async def test_timer_state_machine_fired():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t")
    completed = DecisionFuture[None]()
    m = TimerStateMachine(attrs, completed)

    m.handle_started(history.TimerStartedEventAttributes(timer_id="t"))
    m.handle_fired(history.TimerFiredEventAttributes())

    assert completed.done() is True
    assert m.get_decision() is None


async def test_timer_state_machine_cancel_after_fired():
    attrs = decision.StartTimerDecisionAttributes(timer_id="t")
    completed = DecisionFuture[None]()
    m = TimerStateMachine(attrs, completed)

    m.handle_started(history.TimerStartedEventAttributes(timer_id="t"))
    m.handle_fired(history.TimerFiredEventAttributes())
    res = m.request_cancel()

    assert res is False
    assert completed.done() is True
    assert m.get_decision() is None
