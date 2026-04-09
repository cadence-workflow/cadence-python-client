"""Tests for signal handling in the workflow engine."""

from datetime import timedelta

import pytest

from cadence.api.v1.common_pb2 import ActivityType, Payload
from cadence.api.v1.history_pb2 import (
    ActivityTaskCompletedEventAttributes,
    ActivityTaskScheduledEventAttributes,
    ActivityTaskStartedEventAttributes,
    DecisionTaskCompletedEventAttributes,
    DecisionTaskScheduledEventAttributes,
    DecisionTaskStartedEventAttributes,
    HistoryEvent,
    WorkflowExecutionStartedEventAttributes,
    WorkflowExecutionSignaledEventAttributes,
)
from cadence._internal.workflow.workflow_engine import WorkflowEngine
from cadence import workflow
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo, WorkflowDefinition, WorkflowDefinitionOptions


# ── Test Workflows ──────────────────────────────────────────────────────


class SignalWorkflow:
    def __init__(self):
        self.signals_received: list[str] = []

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: len(self.signals_received) >= 1)
        return self.signals_received[0]

    @workflow.signal(name="my_signal")
    def handle_signal(self, value: str):
        self.signals_received.append(value)


class MultiSignalWorkflow:
    def __init__(self):
        self.signals_received: list[str] = []

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: len(self.signals_received) >= 3)
        return ",".join(self.signals_received)

    @workflow.signal(name="append")
    def handle_append(self, value: str):
        self.signals_received.append(value)


class NoArgSignalWorkflow:
    def __init__(self):
        self.notified = False

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: self.notified)
        return "notified"

    @workflow.signal(name="notify")
    def handle_notify(self):
        self.notified = True


class AsyncSignalWorkflow:
    def __init__(self):
        self.signals_received: list[str] = []

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: len(self.signals_received) >= 1)
        return self.signals_received[0]

    @workflow.signal(name="async_signal")
    async def handle_signal(self, value: str):
        self.signals_received.append(value)


class MultiParamSignalWorkflow:
    def __init__(self):
        self.result: str = ""

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: self.result != "")
        return self.result

    @workflow.signal(name="set_result")
    def handle_signal(self, name: str, count: int):
        self.result = f"{name}:{count}"


class WaitConditionAlreadyTrueWorkflow:
    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: True)
        return "done"


class MultipleWaitersWorkflow:
    def __init__(self):
        self.a_done = False
        self.b_done = False

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: self.a_done and self.b_done)
        return "both_done"

    @workflow.signal(name="signal_a")
    def handle_a(self):
        self.a_done = True

    @workflow.signal(name="signal_b")
    def handle_b(self):
        self.b_done = True


class ActivityCompletionAndSignalWorkflow:
    def __init__(self):
        self.log: list[str] = []

    @workflow.run
    async def run(self):
        result = await workflow.execute_activity(
            "act", str, schedule_to_close_timeout=timedelta(seconds=1)
        )
        self.log.append(f"activity:{result}")
        await workflow.wait_condition(lambda: len(self.log) >= 2)
        return ",".join(self.log)

    @workflow.signal(name="sig")
    def handle_signal(self):
        self.log.append("signal")


# ── Helpers ─────────────────────────────────────────────────────────────

DATA_CONVERTER = DefaultDataConverter()


def make_workflow_engine(workflow_cls) -> WorkflowEngine:
    workflow_def = WorkflowDefinition.wrap(
        workflow_cls, WorkflowDefinitionOptions(name=workflow_cls.__name__)
    )
    return WorkflowEngine(
        info=WorkflowInfo(
            workflow_type=workflow_cls.__name__,
            workflow_domain="test-domain",
            workflow_id="test-workflow-id",
            workflow_run_id="test-run-id",
            workflow_task_list="test-task-list",
            data_converter=DATA_CONVERTER,
        ),
        workflow_definition=workflow_def,
    )


def start_events(input_payload: Payload | None = None) -> list[HistoryEvent]:
    """Workflow start + decision task started (non-replay, no completed event)."""
    if input_payload is None:
        input_payload = Payload(data=b"[]")
    return [
        HistoryEvent(
            event_id=1,
            workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                input=input_payload,
            ),
        ),
        HistoryEvent(
            event_id=2,
            decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
        ),
        HistoryEvent(
            event_id=3,
            decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                scheduled_event_id=2,
            ),
        ),
    ]


def signal_event(event_id: int, signal_name: str, *args) -> HistoryEvent:
    payload = DATA_CONVERTER.to_data(list(args))
    return HistoryEvent(
        event_id=event_id,
        workflow_execution_signaled_event_attributes=WorkflowExecutionSignaledEventAttributes(
            signal_name=signal_name,
            input=payload,
        ),
    )


def signal_event_no_payload(event_id: int, signal_name: str) -> HistoryEvent:
    return HistoryEvent(
        event_id=event_id,
        workflow_execution_signaled_event_attributes=WorkflowExecutionSignaledEventAttributes(
            signal_name=signal_name,
        ),
    )


def activity_scheduled_event(event_id: int, activity_id: str) -> HistoryEvent:
    return HistoryEvent(
        event_id=event_id,
        activity_task_scheduled_event_attributes=ActivityTaskScheduledEventAttributes(
            activity_id=activity_id,
            activity_type=ActivityType(name="act"),
        ),
    )


def activity_started_event(event_id: int, scheduled_event_id: int) -> HistoryEvent:
    return HistoryEvent(
        event_id=event_id,
        activity_task_started_event_attributes=ActivityTaskStartedEventAttributes(
            scheduled_event_id=scheduled_event_id,
        ),
    )


def activity_completed_event(
    event_id: int, scheduled_event_id: int, result: str
) -> HistoryEvent:
    return HistoryEvent(
        event_id=event_id,
        activity_task_completed_event_attributes=ActivityTaskCompletedEventAttributes(
            scheduled_event_id=scheduled_event_id,
            result=DATA_CONVERTER.to_data([result]),
        ),
    )


# ── Tests ───────────────────────────────────────────────────────────────


class TestSignalDelivery:
    """Tests for signal event dispatch and handler invocation."""

    def test_single_signal_delivered(self):
        """A single signal is dispatched to the correct handler and unblocks wait_condition."""
        engine = make_workflow_engine(SignalWorkflow)
        events = start_events()
        # Insert signal before decision task started
        events.insert(1, signal_event(2, "my_signal", "hello"))
        # Adjust event IDs for subsequent events
        events[2] = HistoryEvent(
            event_id=3,
            decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
        )
        events[3] = HistoryEvent(
            event_id=4,
            decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                scheduled_event_id=3,
            ),
        )

        result = engine.process_decision(events)
        assert engine.is_done()
        assert len(result.decisions) == 1
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["hello"]

    def test_multiple_signals_delivered_in_order(self):
        """Multiple signals are delivered in history order."""
        engine = make_workflow_engine(MultiSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "append", "first"),
            signal_event(3, "append", "second"),
            signal_event(4, "append", "third"),
            HistoryEvent(
                event_id=5,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=6,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=5,
                ),
            ),
        ]

        result = engine.process_decision(events)
        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == [
            "first,second,third"
        ]

    def test_signal_with_empty_payload(self):
        """Signal handler with no parameters works with empty payload."""
        engine = make_workflow_engine(NoArgSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event_no_payload(2, "notify"),
            HistoryEvent(
                event_id=3,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=3,
                ),
            ),
        ]

        result = engine.process_decision(events)
        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["notified"]

    def test_async_signal_handler_raises(self):
        engine = make_workflow_engine(AsyncSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "async_signal", "async_value"),
            HistoryEvent(
                event_id=3,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=3,
                ),
            ),
        ]

        with pytest.raises(NotImplementedError, match="Async signal handlers"):
            engine.process_decision(events)

    def test_multi_param_signal(self):
        """Signal handler with multiple typed parameters decodes correctly."""
        engine = make_workflow_engine(MultiParamSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "set_result", "alice", 42),
            HistoryEvent(
                event_id=3,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=3,
                ),
            ),
        ]

        result = engine.process_decision(events)
        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["alice:42"]

    def test_unknown_signal_dropped(self):
        """Unknown signal name logs warning and doesn't crash."""
        engine = make_workflow_engine(NoArgSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "nonexistent_signal", "data"),
            signal_event_no_payload(3, "notify"),  # real signal to unblock workflow
            HistoryEvent(
                event_id=4,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=5,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=4,
                ),
            ),
        ]

        result = engine.process_decision(events)
        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["notified"]


class TestSameBatchOrdering:
    """Tests that signals in the same batch as workflow start are applied before workflow runs."""

    def test_same_batch_start_and_signal(self):
        """Signal in same batch as WorkflowExecutionStarted is visible to workflow."""
        engine = make_workflow_engine(SignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "my_signal", "same_batch_value"),
            HistoryEvent(
                event_id=3,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=3,
                ),
            ),
        ]

        result = engine.process_decision(events)
        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == [
            "same_batch_value"
        ]

    def test_input_events_are_consumed_in_history_order(self, monkeypatch):
        """Signals are encountered in history order, not drained in a separate pre-pass."""
        engine = make_workflow_engine(NoArgSignalWorkflow)
        seen: list[str] = []

        def fake_apply_input_event(event: HistoryEvent) -> None:
            seen.append(event.WhichOneof("attributes"))

        def fake_handle_signal_event(event: HistoryEvent, _on_applied) -> None:
            seen.append(event.WhichOneof("attributes"))

        monkeypatch.setattr(engine, "_apply_input_event", fake_apply_input_event)
        monkeypatch.setattr(
            engine._workflow_instance, "handle_signal_event", fake_handle_signal_event
        )
        monkeypatch.setattr(engine._workflow_instance, "run_until_yield", lambda: None)
        monkeypatch.setattr(engine, "_maybe_complete_workflow", lambda: None)

        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event_no_payload(2, "notify"),
            HistoryEvent(
                event_id=3,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=3,
                ),
            ),
        ]

        engine.process_decision(events)

        assert seen == [
            "workflow_execution_started_event_attributes",
            "workflow_execution_signaled_event_attributes",
            "decision_task_scheduled_event_attributes",
        ]


class TestWaitCondition:
    """Tests for workflow.wait_condition behavior."""

    def test_predicate_already_true(self):
        """wait_condition returns immediately when predicate is already True."""
        engine = make_workflow_engine(WaitConditionAlreadyTrueWorkflow)
        events = start_events()

        result = engine.process_decision(events)
        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["done"]

    def test_predicate_false_then_true_after_signal(self):
        """Workflow blocks on wait_condition, signal makes predicate true, workflow resumes."""
        engine = make_workflow_engine(SignalWorkflow)

        # First decision: workflow starts and blocks on wait_condition
        events_1 = start_events()
        result_1 = engine.process_decision(events_1)
        assert not engine.is_done()
        assert len(result_1.decisions) == 0

        # Second decision: signal arrives, workflow completes
        events_2 = [
            signal_event(4, "my_signal", "wakeup"),
            HistoryEvent(
                event_id=5,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=6,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=5,
                ),
            ),
        ]

        result_2 = engine.process_decision(events_2)
        assert engine.is_done()
        completion = result_2.decisions[
            0
        ].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["wakeup"]

    def test_multiple_signals_needed(self):
        """Workflow waits for multiple signals before proceeding."""
        engine = make_workflow_engine(MultipleWaitersWorkflow)

        # First decision: workflow starts, blocks waiting for both signals
        events_1 = start_events()
        result_1 = engine.process_decision(events_1)
        assert not engine.is_done()
        assert len(result_1.decisions) == 0

        # Second decision: only signal_a arrives, still blocked
        events_2 = [
            signal_event_no_payload(4, "signal_a"),
            HistoryEvent(
                event_id=5,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=6,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=5,
                ),
            ),
        ]
        result_2 = engine.process_decision(events_2)
        assert not engine.is_done()
        assert len(result_2.decisions) == 0

        # Third decision: signal_b arrives, workflow completes
        events_3 = [
            signal_event_no_payload(7, "signal_b"),
            HistoryEvent(
                event_id=8,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=9,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=8,
                ),
            ),
        ]
        result_3 = engine.process_decision(events_3)
        assert engine.is_done()
        completion = result_3.decisions[
            0
        ].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["both_done"]

    def test_both_signals_same_batch(self):
        """Both signals in the same batch unblock wait_condition for compound predicate."""
        engine = make_workflow_engine(MultipleWaitersWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event_no_payload(2, "signal_a"),
            signal_event_no_payload(3, "signal_b"),
            HistoryEvent(
                event_id=4,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=5,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=4,
                ),
            ),
        ]

        result = engine.process_decision(events)
        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["both_done"]

    def test_signal_callback_preempts_resumed_workflow_task(self):
        """Signal callbacks run before a workflow task resumed by an earlier activity completion."""
        engine = make_workflow_engine(ActivityCompletionAndSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            HistoryEvent(
                event_id=2,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=3,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=2,
                ),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_completed_event_attributes=DecisionTaskCompletedEventAttributes(
                    scheduled_event_id=2,
                ),
            ),
            activity_scheduled_event(5, "0"),
            activity_started_event(6, 5),
            activity_completed_event(7, 5, "done"),
            signal_event_no_payload(8, "sig"),
            HistoryEvent(
                event_id=9,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=10,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=9,
                ),
            ),
        ]

        result = engine.process_decision(events)

        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == [
            "signal,activity:done"
        ]


class TestReplay:
    """Tests that signal handling works correctly during replay."""

    def test_signal_replay_produces_same_result(self):
        """Replaying the same signal history produces identical state."""
        # First run: start + signal in one batch
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "my_signal", "replayed_value"),
            HistoryEvent(
                event_id=3,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=3,
                ),
            ),
        ]

        engine1 = make_workflow_engine(SignalWorkflow)
        result1 = engine1.process_decision(events)

        engine2 = make_workflow_engine(SignalWorkflow)
        result2 = engine2.process_decision(events)

        r1 = result1.decisions[0].complete_workflow_execution_decision_attributes.result
        r2 = result2.decisions[0].complete_workflow_execution_decision_attributes.result
        assert r1 == r2
        assert DATA_CONVERTER.from_data(r1, [str]) == ["replayed_value"]

    def test_signal_replay_with_decision_completed(self):
        """Replay through a completed decision batch followed by new signal."""
        engine = make_workflow_engine(SignalWorkflow)

        # Full replay: first decision batch (workflow started, blocked)
        # Then second batch with signal
        events = [
            # First batch: workflow starts, no signal, blocks
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            HistoryEvent(
                event_id=2,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=3,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=2,
                ),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_completed_event_attributes=DecisionTaskCompletedEventAttributes(
                    scheduled_event_id=2,
                ),
            ),
            # Second batch: signal arrives
            signal_event(5, "my_signal", "after_replay"),
            HistoryEvent(
                event_id=6,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=7,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=6,
                ),
            ),
        ]

        result = engine.process_decision(events)
        assert engine.is_done()
        completion = result.decisions[0].complete_workflow_execution_decision_attributes
        assert DATA_CONVERTER.from_data(completion.result, [str]) == ["after_replay"]
