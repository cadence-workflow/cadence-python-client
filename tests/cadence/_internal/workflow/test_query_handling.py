"""Tests for query handling in the workflow engine."""

import pytest

from cadence import workflow
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.history_pb2 import (
    DecisionTaskCompletedEventAttributes,
    DecisionTaskScheduledEventAttributes,
    DecisionTaskStartedEventAttributes,
    HistoryEvent,
    WorkflowExecutionStartedEventAttributes,
    WorkflowExecutionSignaledEventAttributes,
)
from cadence.api.v1.query_pb2 import (
    WorkflowQuery,
    QUERY_RESULT_TYPE_ANSWERED,
    QUERY_RESULT_TYPE_FAILED,
)
from cadence._internal.workflow.workflow_engine import WorkflowEngine
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo, WorkflowDefinition, WorkflowDefinitionOptions


# ── Test Workflows ──────────────────────────────────────────────────────


class QueryWorkflow:
    def __init__(self):
        self.status = "running"
        self.count = 0

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: self.status == "done")
        return self.status

    @workflow.signal(name="increment")
    def handle_increment(self):
        self.count += 1

    @workflow.signal(name="set_status")
    def handle_set_status(self, status: str):
        self.status = status

    @workflow.query(name="get_status")
    def get_status(self) -> str:
        return self.status

    @workflow.query(name="get_count")
    def get_count(self) -> int:
        return self.count


class QueryWithArgsWorkflow:
    def __init__(self):
        self.data: dict[str, int] = {"a": 1, "b": 2, "c": 3}

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: False)
        return "unreachable"

    @workflow.query(name="get_value")
    def get_value(self, key: str) -> int:
        return self.data.get(key, -1)

    @workflow.query(name="get_sum")
    def get_sum(self, key1: str, key2: str) -> int:
        return self.data.get(key1, 0) + self.data.get(key2, 0)


class QueryWithDefaultArgWorkflow:
    def __init__(self):
        self.items = ["a", "b", "c", "d", "e"]

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: False)
        return "unreachable"

    @workflow.query(name="get_items")
    def get_items(self, limit: int = 3) -> str:
        return ",".join(self.items[:limit])


class NoQueryWorkflow:
    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: False)
        return "unreachable"


class QueryAfterSignalWorkflow:
    def __init__(self):
        self.messages: list[str] = []

    @workflow.run
    async def run(self):
        await workflow.wait_condition(lambda: "stop" in self.messages)
        return ",".join(self.messages)

    @workflow.signal(name="add_message")
    def handle_add_message(self, msg: str):
        self.messages.append(msg)

    @workflow.query(name="get_messages")
    def get_messages(self) -> str:
        return ",".join(self.messages)

    @workflow.query(name="get_message_count")
    def get_message_count(self) -> int:
        return len(self.messages)


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


def make_query(query_type: str, *args) -> WorkflowQuery:
    """Create a WorkflowQuery proto with encoded args."""
    query = WorkflowQuery(query_type=query_type)
    if args:
        query.query_args.CopyFrom(DATA_CONVERTER.to_data(list(args)))
    return query


# ── Tests ───────────────────────────────────────────────────────────────


class TestQueryExecution:
    """Tests for executing queries via the legacy query task path."""

    def test_simple_query_returns_initial_state(self):
        """Query returns the initial workflow state before any signals."""
        engine = make_workflow_engine(QueryWorkflow)
        events = start_events()
        query = make_query("get_status")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [str])
        assert decoded == ["running"]

    def test_query_count_returns_zero_initially(self):
        """Query returns initial count of zero."""
        engine = make_workflow_engine(QueryWorkflow)
        events = start_events()
        query = make_query("get_count")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [int])
        assert decoded == [0]

    def test_query_reflects_state_after_signals(self):
        """Query sees state mutated by signals that preceded it in history."""
        engine = make_workflow_engine(QueryAfterSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "add_message", "hello"),
            signal_event(3, "add_message", "world"),
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
        query = make_query("get_messages")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [str])
        assert decoded == ["hello,world"]

    def test_query_with_arguments(self):
        """Query handler receives and uses arguments correctly."""
        engine = make_workflow_engine(QueryWithArgsWorkflow)
        events = start_events()
        query = make_query("get_value", "b")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [int])
        assert decoded == [2]

    def test_query_with_multiple_arguments(self):
        """Query handler with multiple args works correctly."""
        engine = make_workflow_engine(QueryWithArgsWorkflow)
        events = start_events()
        query = make_query("get_sum", "a", "c")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [int])
        assert decoded == [4]

    def test_query_with_default_argument_omitted(self):
        """Query handler uses Python default when arg is omitted from payload."""
        engine = make_workflow_engine(QueryWithDefaultArgWorkflow)
        events = start_events()
        query = make_query("get_items")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [str])
        assert decoded == ["a,b,c"]

    def test_query_with_default_argument_overridden(self):
        """Query handler uses provided value over Python default."""
        engine = make_workflow_engine(QueryWithDefaultArgWorkflow)
        events = start_events()
        query = make_query("get_items", 5)

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [str])
        assert decoded == ["a,b,c,d,e"]

    def test_unknown_query_type_returns_failed(self):
        """Querying an unregistered query type returns QUERY_RESULT_TYPE_FAILED."""
        engine = make_workflow_engine(QueryWorkflow)
        events = start_events()
        query = make_query("nonexistent_query")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_FAILED
        assert "Unknown query type 'nonexistent_query'" in result.error_message

    def test_query_on_workflow_with_no_query_handlers(self):
        """Querying a workflow with no registered handlers returns FAILED."""
        engine = make_workflow_engine(NoQueryWorkflow)
        events = start_events()
        query = make_query("get_status")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_FAILED
        assert "Unknown query type" in result.error_message


class TestQueryAfterReplay:
    """Tests that queries see the correct state after replaying history."""

    def test_query_after_replay_through_completed_decision(self):
        """Query executes against state replayed through a completed decision batch."""
        engine = make_workflow_engine(QueryAfterSignalWorkflow)
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
            signal_event(5, "add_message", "after_first_decision"),
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
        query = make_query("get_message_count")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [int])
        assert decoded == [1]

    def test_query_sees_all_signals_in_history(self):
        """Query reflects all signals accumulated across multiple decision batches."""
        engine = make_workflow_engine(QueryAfterSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "add_message", "first"),
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
            HistoryEvent(
                event_id=5,
                decision_task_completed_event_attributes=DecisionTaskCompletedEventAttributes(
                    scheduled_event_id=3,
                ),
            ),
            signal_event(6, "add_message", "second"),
            signal_event(7, "add_message", "third"),
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
        query = make_query("get_messages")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(result.answer, [str])
        assert decoded == ["first,second,third"]


class TestInlineQueries:
    """Tests for inline queries (answered as part of a normal decision task)."""

    def test_inline_query_answered_alongside_decisions(self):
        """Inline queries return results in DecisionResult.query_results."""
        engine = make_workflow_engine(QueryWorkflow)
        events = start_events()
        queries = {"q1": make_query("get_status")}

        result = engine.process_decision(events, queries=queries)

        assert "q1" in result.query_results
        q1_result = result.query_results["q1"]
        assert q1_result.result_type == QUERY_RESULT_TYPE_ANSWERED
        decoded = DATA_CONVERTER.from_data(q1_result.answer, [str])
        assert decoded == ["running"]

    def test_multiple_inline_queries(self):
        """Multiple inline queries are each answered independently."""
        engine = make_workflow_engine(QueryWorkflow)
        events = start_events()
        queries = {
            "q1": make_query("get_status"),
            "q2": make_query("get_count"),
        }

        result = engine.process_decision(events, queries=queries)

        assert len(result.query_results) == 2

        q1_result = result.query_results["q1"]
        assert q1_result.result_type == QUERY_RESULT_TYPE_ANSWERED
        assert DATA_CONVERTER.from_data(q1_result.answer, [str]) == ["running"]

        q2_result = result.query_results["q2"]
        assert q2_result.result_type == QUERY_RESULT_TYPE_ANSWERED
        assert DATA_CONVERTER.from_data(q2_result.answer, [int]) == [0]

    def test_inline_query_with_unknown_type_returns_failed(self):
        """Unknown query type in inline queries returns FAILED without crashing."""
        engine = make_workflow_engine(QueryWorkflow)
        events = start_events()
        queries = {
            "q1": make_query("get_status"),
            "q2": make_query("nonexistent"),
        }

        result = engine.process_decision(events, queries=queries)

        q1_result = result.query_results["q1"]
        assert q1_result.result_type == QUERY_RESULT_TYPE_ANSWERED

        q2_result = result.query_results["q2"]
        assert q2_result.result_type == QUERY_RESULT_TYPE_FAILED
        assert "Unknown query type" in q2_result.error_message

    def test_no_inline_queries_produces_empty_results(self):
        """When no inline queries are provided, query_results is empty."""
        engine = make_workflow_engine(QueryWorkflow)
        events = start_events()

        result = engine.process_decision(events)

        assert result.query_results == {}

    def test_inline_query_after_signals_reflects_state(self):
        """Inline queries see state after all signals are processed."""
        engine = make_workflow_engine(QueryAfterSignalWorkflow)
        events = [
            HistoryEvent(
                event_id=1,
                workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                    input=Payload(data=b"[]"),
                ),
            ),
            signal_event(2, "add_message", "hello"),
            signal_event(3, "add_message", "world"),
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
        queries = {"q1": make_query("get_message_count")}

        result = engine.process_decision(events, queries=queries)

        q1_result = result.query_results["q1"]
        assert q1_result.result_type == QUERY_RESULT_TYPE_ANSWERED
        assert DATA_CONVERTER.from_data(q1_result.answer, [int]) == [2]


class TestQueryDefinitionValidation:
    """Tests for query definition-time validation."""

    def test_query_must_have_return_type(self):
        """Query handlers with None return type are rejected at definition time."""
        from cadence.query import QueryDefinition, QueryDefinitionOptions

        def bad_handler(self, x: int) -> None:
            pass

        with pytest.raises(ValueError, match="must have a non-None return type"):
            QueryDefinition.wrap(bad_handler, QueryDefinitionOptions(name="test"))

    def test_query_with_valid_return_type_accepted(self):
        """Query handlers with non-None return type are accepted."""
        from cadence.query import QueryDefinition, QueryDefinitionOptions

        def good_handler(self, x: int) -> str:
            return str(x)

        qdef = QueryDefinition.wrap(good_handler, QueryDefinitionOptions(name="test"))
        assert qdef.name == "test"
        assert qdef.wrapped is good_handler

    def test_duplicate_query_names_rejected(self):
        """Multiple @workflow.query with the same name raises ValueError."""

        with pytest.raises(ValueError, match="Multiple @workflow.query methods"):

            class BadWorkflow:
                @workflow.run
                async def run(self):
                    pass

                @workflow.query(name="same_name")
                def query_a(self) -> str:
                    return "a"

                @workflow.query(name="same_name")
                def query_b(self) -> str:
                    return "b"

            WorkflowDefinition.wrap(
                BadWorkflow, WorkflowDefinitionOptions(name="BadWorkflow")
            )

    def test_query_name_required(self):
        """@workflow.query raises ValueError when name is not provided."""
        with pytest.raises(ValueError, match="name is required"):
            workflow.query(name=None)  # type: ignore

    def test_workflow_definition_includes_queries(self):
        """WorkflowDefinition.queries contains registered query handlers."""
        workflow_def = WorkflowDefinition.wrap(
            QueryWorkflow, WorkflowDefinitionOptions(name="QueryWorkflow")
        )
        assert "get_status" in workflow_def.queries
        assert "get_count" in workflow_def.queries
        assert len(workflow_def.queries) == 2

    def test_workflow_definition_includes_both_signals_and_queries(self):
        """WorkflowDefinition correctly separates signals from queries."""
        workflow_def = WorkflowDefinition.wrap(
            QueryAfterSignalWorkflow,
            WorkflowDefinitionOptions(name="QueryAfterSignalWorkflow"),
        )
        assert "add_message" in workflow_def.signals
        assert "get_messages" in workflow_def.queries
        assert "get_message_count" in workflow_def.queries


class TestQueryHandlerException:
    """Tests for query handler exceptions."""

    def test_query_handler_exception_returns_failed_result(self):
        """An exception in the query handler returns QUERY_RESULT_TYPE_FAILED."""

        class FailingQueryWorkflow:
            @workflow.run
            async def run(self):
                await workflow.wait_condition(lambda: False)
                return "unreachable"

            @workflow.query(name="failing_query")
            def failing_query(self) -> str:
                raise RuntimeError("query handler error")

        engine = make_workflow_engine(FailingQueryWorkflow)
        events = start_events()
        query = make_query("failing_query")

        result = engine.execute_query(query, events)

        assert result.result_type == QUERY_RESULT_TYPE_FAILED
        assert "query handler error" in result.error_message
