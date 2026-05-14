import asyncio
from datetime import timedelta
from typing import Any, Literal, cast

from cadence import Registry, workflow
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()


@registry.workflow()
class QuerySimpleWorkflow:
    """Workflow with a simple query that returns initial state."""

    def __init__(self) -> None:
        self.status = "running"

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self.status == "done")
        return self.status

    @workflow.query(name="get_status")
    def get_status(self) -> str:
        return self.status

    @workflow.signal(name="set_status")
    def set_status(self, status: str) -> None:
        self.status = status


@registry.workflow()
class QueryWithArgsWorkflow:
    """Workflow whose query handler accepts arguments."""

    def __init__(self) -> None:
        self.data: dict[str, int] = {"a": 1, "b": 2, "c": 3}

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: "stop" in self.data)
        return "done"

    @workflow.query(name="get_value")
    def get_value(self, key: str) -> int:
        return self.data.get(key, -1)

    @workflow.signal(name="put")
    def put(self, key: str, value: int) -> None:
        self.data[key] = value


@registry.workflow()
class QueryMultipleHandlersWorkflow:
    """Workflow with multiple query handlers."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.done = False

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self.done)
        return ",".join(self.messages)

    @workflow.query(name="get_messages")
    def get_messages(self) -> str:
        return ",".join(self.messages)

    @workflow.query(name="get_count")
    def get_count(self) -> int:
        return len(self.messages)

    @workflow.signal(name="add")
    def add(self, msg: str) -> None:
        self.messages.append(msg)

    @workflow.signal(name="finish")
    def finish(self) -> None:
        self.done = True


def _scan_workflow_outcome(
    response: GetWorkflowExecutionHistoryResponse,
) -> (
    tuple[Literal["completed"], str]
    | tuple[Literal["timed_out"], None]
    | tuple[Literal["failed"], None]
    | tuple[Literal["running"], None]
):
    for event in reversed(response.history.events):
        if event.HasField("workflow_execution_completed_event_attributes"):
            return (
                "completed",
                cast(
                    str,
                    event.workflow_execution_completed_event_attributes.result.data.decode(),
                ),
            )
        if event.HasField("workflow_execution_timed_out_event_attributes"):
            return ("timed_out", None)
        if event.HasField("workflow_execution_failed_event_attributes"):
            return ("failed", None)
    return ("running", None)


async def _get_full_history(
    helper: CadenceHelper, execution: Any
) -> GetWorkflowExecutionHistoryResponse:
    async with helper.client() as client:
        return cast(
            GetWorkflowExecutionHistoryResponse,
            await client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=DOMAIN_NAME,
                    workflow_execution=execution,
                    skip_archival=True,
                )
            ),
        )


async def _wait_for_workflow_result(
    helper: CadenceHelper,
    execution: Any,
    *,
    deadline_seconds: float = 30.0,
) -> str:
    """Poll full history until the run completes (or times out / fails on the server)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    last: GetWorkflowExecutionHistoryResponse | None = None
    while loop.time() < deadline:
        last = await _get_full_history(helper, execution)
        status, data = _scan_workflow_outcome(last)
        if status == "completed":
            assert data is not None
            return data
        if status == "timed_out":
            raise AssertionError(
                "Workflow execution timed out before completion"
            )
        if status == "failed":
            raise AssertionError("Workflow execution failed")
        await asyncio.sleep(0.05)
    raise AssertionError(
        "Timed out waiting for workflow completion in history"
        + (
            f" (last event id {last.history.events[-1].event_id})"
            if last and last.history.events
            else ""
        )
    )


async def _poll_query(
    helper: CadenceHelper,
    workflow_id: str,
    run_id: str,
    query_type: str,
    *args: Any,
    result_type: type = str,
    deadline_seconds: float = 15.0,
) -> Any:
    """Retry a query until it succeeds or the deadline expires.

    The first decision task may not have been processed yet when
    we issue the query, so we retry on transient failures.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    last_err: Exception | None = None
    while loop.time() < deadline:
        try:
            async with helper.client() as client:
                return await client.query_workflow(
                    workflow_id,
                    run_id,
                    query_type,
                    *args,
                    result_type=result_type,
                )
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.2)
    raise AssertionError(
        f"Query '{query_type}' did not succeed within {deadline_seconds}s"
    ) from last_err


async def test_query_returns_initial_state(helper: CadenceHelper):
    """Query a running workflow and verify the initial state is returned."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "QuerySimpleWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        result = await _poll_query(
            helper,
            execution.workflow_id,
            execution.run_id,
            "get_status",
        )
        assert result == "running"

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "set_status",
            "done",
        )
        await _wait_for_workflow_result(helper, execution)


async def test_query_reflects_signal_mutations(helper: CadenceHelper):
    """Query sees state changes made by signals."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "QuerySimpleWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        await _poll_query(
            helper,
            execution.workflow_id,
            execution.run_id,
            "get_status",
        )

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "set_status",
            "processing",
        )

        # Wait until the query reflects the mutated state
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15.0
        while loop.time() < deadline:
            result = await _poll_query(
                helper,
                execution.workflow_id,
                execution.run_id,
                "get_status",
            )
            if result == "processing":
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("Query never reflected 'processing' status")

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "set_status",
            "done",
        )
        await _wait_for_workflow_result(helper, execution)


async def test_query_with_arguments(helper: CadenceHelper):
    """Query handler correctly receives and uses arguments."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "QueryWithArgsWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        result = await _poll_query(
            helper,
            execution.workflow_id,
            execution.run_id,
            "get_value",
            "b",
            result_type=int,
        )
        assert result == 2

        result = await _poll_query(
            helper,
            execution.workflow_id,
            execution.run_id,
            "get_value",
            "missing",
            result_type=int,
        )
        assert result == -1

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "put",
            "stop",
            0,
        )
        await _wait_for_workflow_result(helper, execution)


async def test_multiple_query_handlers(helper: CadenceHelper):
    """Multiple independent query handlers work on the same workflow."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "QueryMultipleHandlersWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        count = await _poll_query(
            helper,
            execution.workflow_id,
            execution.run_id,
            "get_count",
            result_type=int,
        )
        assert count == 0

        for msg in ("hello", "world"):
            await worker.client.signal_workflow(
                execution.workflow_id,
                execution.run_id,
                "add",
                msg,
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15.0
        while loop.time() < deadline:
            count = await _poll_query(
                helper,
                execution.workflow_id,
                execution.run_id,
                "get_count",
                result_type=int,
            )
            if count == 2:
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("get_count never reached 2")

        messages = await _poll_query(
            helper,
            execution.workflow_id,
            execution.run_id,
            "get_messages",
        )
        assert messages == "hello,world"

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "finish",
        )
        await _wait_for_workflow_result(helper, execution)
