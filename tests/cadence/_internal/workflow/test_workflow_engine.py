#!/usr/bin/env python3
import asyncio
from datetime import timedelta
from typing import List

import pytest
from cadence.api.v1.common_pb2 import ActivityType, Payload, WorkflowType
from cadence.api.v1.decision_pb2 import CancelWorkflowExecutionDecisionAttributes
from cadence.api.v1.history_pb2 import (
    ActivityTaskScheduledEventAttributes,
    DecisionTaskCompletedEventAttributes,
    DecisionTaskScheduledEventAttributes,
    DecisionTaskStartedEventAttributes,
    HistoryEvent,
    StartChildWorkflowExecutionInitiatedEventAttributes,
    TimerStartedEventAttributes,
    WorkflowExecutionCancelRequestedEventAttributes,
    WorkflowExecutionCompletedEventAttributes,
    WorkflowExecutionStartedEventAttributes,
)
from cadence._internal.workflow.workflow_engine import WorkflowEngine
from cadence import workflow
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo, WorkflowDefinition, WorkflowDefinitionOptions


class TestWorkflow:
    @workflow.run
    async def echo(self, input_data):
        return f"echo: {input_data}"


class CancellationInfoWorkflow:
    @workflow.run
    async def run(self):
        try:
            await workflow.wait_condition(lambda: False)
        except asyncio.CancelledError:
            pass
        info = workflow.cancellation_info()
        assert info is not None
        return {
            "requested": workflow.is_cancel_requested(),
            "cause": info.cause,
            "identity": info.identity,
            "request_id": info.request_id,
        }


class UncaughtCancellationWorkflow:
    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: False)
        return "unreachable"


class CaughtCancellationWorkflow:
    @workflow.run
    async def run(self):
        try:
            await workflow.wait_condition(lambda: False)
        except asyncio.CancelledError as e:
            return f"caught:{e.args[0]}"
        return "unreachable"


class CleanupCancellationWorkflow:
    @workflow.run
    async def run(self):
        try:
            await workflow.wait_condition(lambda: False)
        except asyncio.CancelledError:
            info = workflow.cancellation_info()
            assert info is not None
            return f"cleanup:{info.cause}:{workflow.is_cancel_requested()}"
        return "unreachable"


class PendingActivityCancellationWorkflow:
    @workflow.run
    async def run(self):
        try:
            await workflow.execute_activity(
                "act", str, schedule_to_close_timeout=timedelta(minutes=5)
            )
        except asyncio.CancelledError as e:
            arg = e.args[0] if e.args else ""
            return f"activity-cancelled:{arg}"
        return "unreachable"


class PendingTimerCancellationWorkflow:
    @workflow.run
    async def run(self):
        try:
            await workflow.sleep(timedelta(minutes=5))
        except asyncio.CancelledError as e:
            arg = e.args[0] if e.args else ""
            return f"timer-cancelled:{arg}"
        return "unreachable"


class PendingChildWorkflowCancellationWorkflow:
    @workflow.run
    async def run(self):
        try:
            await workflow.execute_child_workflow(
                "Child",
                str,
                workflow_id="child",
                execution_start_to_close_timeout=timedelta(minutes=5),
            )
        except asyncio.CancelledError:
            return "child-cancelled"
        return "unreachable"


class TestWorkflowEngine:
    """Unit tests for WorkflowEngine."""

    @pytest.fixture
    def echo_workflow_definition(self) -> WorkflowDefinition:
        """Create a mock workflow definition."""
        workflow_opts = WorkflowDefinitionOptions(name="test_workflow")
        return WorkflowDefinition.wrap(TestWorkflow, workflow_opts)

    @pytest.fixture
    def simple_workflow_events(self) -> List[HistoryEvent]:
        return [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b'"test-input"')
                ),
            ),
            HistoryEvent(
                event_id=2,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            HistoryEvent(
                event_id=3,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=2
                ),
            ),
            HistoryEvent(
                event_id=4,
                decision_task_completed_event_attributes=DecisionTaskCompletedEventAttributes(
                    scheduled_event_id=2,
                ),
            ),
            HistoryEvent(
                event_id=5,
                workflow_execution_completed_event_attributes=WorkflowExecutionCompletedEventAttributes(
                    result=Payload(data=b'"echo: test-input"')
                ),
            ),
        ]

    def test_process_simple_workflow(
        self,
        echo_workflow_definition: WorkflowDefinition,
        simple_workflow_events: List[HistoryEvent],
    ):
        workflow_engine = create_workflow_engine(echo_workflow_definition)
        decision_result = workflow_engine.process_decision(simple_workflow_events[:3])
        assert len(decision_result.decisions) == 1
        assert decision_result.decisions[
            0
        ].complete_workflow_execution_decision_attributes.result == Payload(
            data=b'"echo: test-input"'
        )

    def test_workflow_observes_cancel_requested(self):
        workflow_definition = WorkflowDefinition.wrap(
            CancellationInfoWorkflow,
            WorkflowDefinitionOptions(name="cancel_info_workflow"),
        )
        workflow_engine = create_workflow_engine(workflow_definition)

        workflow_engine.process_decision(
            [
                _event(
                    1,
                    workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(),
                ),
                _event(
                    2,
                    decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
                ),
                _event(
                    3,
                    decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                        scheduled_event_id=2
                    ),
                ),
            ]
        )

        decision_result = workflow_engine.process_decision(
            [
                _event(
                    1,
                    workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(),
                ),
                _event(
                    2,
                    decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
                ),
                _event(
                    3,
                    decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                        scheduled_event_id=2
                    ),
                ),
                _event(
                    4,
                    decision_task_completed_event_attributes=DecisionTaskCompletedEventAttributes(
                        scheduled_event_id=2,
                        started_event_id=3,
                    ),
                ),
                _event(
                    5,
                    workflow_execution_cancel_requested_event_attributes=WorkflowExecutionCancelRequestedEventAttributes(
                        cause="user requested",
                        identity="test-worker",
                        request_id="request-1",
                    ),
                ),
                _event(
                    6,
                    decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
                ),
                _event(
                    7,
                    decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                        scheduled_event_id=6
                    ),
                ),
            ]
        )

        assert len(decision_result.decisions) == 1
        result = decision_result.decisions[
            0
        ].complete_workflow_execution_decision_attributes.result
        assert result == DefaultDataConverter().to_data(
            [
                {
                    "requested": True,
                    "cause": "user requested",
                    "identity": "test-worker",
                    "request_id": "request-1",
                }
            ]
        )

    def test_uncaught_workflow_cancellation_closes_as_canceled(self):
        workflow_engine = create_workflow_engine(
            WorkflowDefinition.wrap(
                UncaughtCancellationWorkflow,
                WorkflowDefinitionOptions(name="uncaught_cancel_workflow"),
            )
        )
        _start_waiting_workflow(workflow_engine)

        decision_result = workflow_engine.process_decision(
            _history_with_cancel_request("user requested")
        )

        assert len(decision_result.decisions) == 1
        assert decision_result.decisions[
            0
        ].cancel_workflow_execution_decision_attributes == (
            CancelWorkflowExecutionDecisionAttributes(
                details=DefaultDataConverter().to_data(["user requested"])
            )
        )

    def test_caught_workflow_cancellation_can_complete(self):
        workflow_engine = create_workflow_engine(
            WorkflowDefinition.wrap(
                CaughtCancellationWorkflow,
                WorkflowDefinitionOptions(name="caught_cancel_workflow"),
            )
        )
        _start_waiting_workflow(workflow_engine)

        decision_result = workflow_engine.process_decision(
            _history_with_cancel_request("user requested")
        )

        assert len(decision_result.decisions) == 1
        assert (
            decision_result.decisions[
                0
            ].complete_workflow_execution_decision_attributes.result
            == DefaultDataConverter().to_data(["caught:user requested"])
        )

    def test_caught_workflow_cancellation_can_run_cleanup(self):
        workflow_engine = create_workflow_engine(
            WorkflowDefinition.wrap(
                CleanupCancellationWorkflow,
                WorkflowDefinitionOptions(name="cleanup_cancel_workflow"),
            )
        )
        _start_waiting_workflow(workflow_engine)

        decision_result = workflow_engine.process_decision(
            _history_with_cancel_request("cleanup requested")
        )

        assert len(decision_result.decisions) == 1
        assert (
            decision_result.decisions[
                0
            ].complete_workflow_execution_decision_attributes.result
            == DefaultDataConverter().to_data(["cleanup:cleanup requested:True"])
        )

    def test_root_cancel_interrupts_pending_activity_and_suppresses_cancel_decision(
        self,
    ):
        workflow_engine = create_workflow_engine(
            WorkflowDefinition.wrap(
                PendingActivityCancellationWorkflow,
                WorkflowDefinitionOptions(name="pending_activity_cancel_workflow"),
            )
        )
        decision_result = workflow_engine.process_decision(
            _history_with_cancel_request(
                "activity cancel",
                output_events=[
                    _event(
                        5,
                        activity_task_scheduled_event_attributes=ActivityTaskScheduledEventAttributes(
                            activity_id="0",
                            activity_type=ActivityType(name="act"),
                        ),
                    )
                ],
            )
        )

        assert len(decision_result.decisions) == 1
        assert (
            decision_result.decisions[
                0
            ].complete_workflow_execution_decision_attributes.result
            == DefaultDataConverter().to_data(["activity-cancelled:activity cancel"])
        )

    def test_root_cancel_interrupts_pending_timer_and_suppresses_cancel_decision(self):
        workflow_engine = create_workflow_engine(
            WorkflowDefinition.wrap(
                PendingTimerCancellationWorkflow,
                WorkflowDefinitionOptions(name="pending_timer_cancel_workflow"),
            )
        )
        decision_result = workflow_engine.process_decision(
            _history_with_cancel_request(
                "timer cancel",
                output_events=[
                    _event(
                        5,
                        timer_started_event_attributes=TimerStartedEventAttributes(
                            timer_id="0"
                        ),
                    )
                ],
            )
        )

        assert len(decision_result.decisions) == 1
        assert (
            decision_result.decisions[
                0
            ].complete_workflow_execution_decision_attributes.result
            == DefaultDataConverter().to_data(["timer-cancelled:timer cancel"])
        )

    def test_root_cancel_interrupts_pending_child_and_suppresses_cancel_decision(self):
        workflow_engine = create_workflow_engine(
            WorkflowDefinition.wrap(
                PendingChildWorkflowCancellationWorkflow,
                WorkflowDefinitionOptions(name="pending_child_cancel_workflow"),
            )
        )
        decision_result = workflow_engine.process_decision(
            _history_with_cancel_request(
                "child cancel",
                output_events=[
                    _event(
                        5,
                        start_child_workflow_execution_initiated_event_attributes=StartChildWorkflowExecutionInitiatedEventAttributes(
                            workflow_id="child",
                            workflow_type=WorkflowType(name="Child"),
                        ),
                    )
                ],
            )
        )

        assert len(decision_result.decisions) == 1
        assert (
            decision_result.decisions[
                0
            ].complete_workflow_execution_decision_attributes.result
            == DefaultDataConverter().to_data(["child-cancelled"])
        )


def create_workflow_engine(workflow_definition: WorkflowDefinition) -> WorkflowEngine:
    """Create workflow engine."""
    return WorkflowEngine(
        info=WorkflowInfo(
            workflow_type="test_workflow",
            workflow_domain="test-domain",
            workflow_id="test-workflow-id",
            workflow_run_id="test-run-id",
            workflow_task_list="test-task-list",
            data_converter=DefaultDataConverter(),
        ),
        workflow_definition=workflow_definition,
    )


def _event(event_id: int, **attributes) -> HistoryEvent:
    event = HistoryEvent(event_id=event_id)
    event.event_time.FromMilliseconds(event_id * 1000)
    for name, value in attributes.items():
        getattr(event, name).CopyFrom(value)
    return event


def _start_waiting_workflow(workflow_engine: WorkflowEngine) -> None:
    workflow_engine.process_decision(
        [
            _event(
                1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(),
            ),
            _event(
                2,
                decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
            ),
            _event(
                3,
                decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                    scheduled_event_id=2
                ),
            ),
        ]
    )


def _history_with_cancel_request(
    cause: str, output_events: list[HistoryEvent] | None = None
) -> list[HistoryEvent]:
    output_events = output_events or []
    cancel_event_id = 5 + len(output_events)
    return [
        _event(
            1,
            workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(),
        ),
        _event(
            2,
            decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
        ),
        _event(
            3,
            decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                scheduled_event_id=2
            ),
        ),
        _event(
            4,
            decision_task_completed_event_attributes=DecisionTaskCompletedEventAttributes(
                scheduled_event_id=2,
                started_event_id=3,
            ),
        ),
        *output_events,
        _event(
            cancel_event_id,
            workflow_execution_cancel_requested_event_attributes=WorkflowExecutionCancelRequestedEventAttributes(
                cause=cause,
                identity="test-worker",
                request_id="request-1",
            ),
        ),
        _event(
            cancel_event_id + 1,
            decision_task_scheduled_event_attributes=DecisionTaskScheduledEventAttributes(),
        ),
        _event(
            cancel_event_id + 2,
            decision_task_started_event_attributes=DecisionTaskStartedEventAttributes(
                scheduled_event_id=cancel_event_id + 1
            ),
        ),
    ]
