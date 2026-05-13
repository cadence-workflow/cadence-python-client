import asyncio
from datetime import timedelta
from typing import Any

from cadence import Registry, workflow
from tests.integration_tests.helper import CadenceHelper

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
