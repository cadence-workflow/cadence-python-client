import asyncio
from datetime import timedelta
from typing import Literal, cast

from cadence import Registry, workflow
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

registry = Registry()


class _SignalWaitBase:
    """Shared signal handler; subclasses fix how many signals unblock ``run``."""

    def __init__(self) -> None:
        self.received: list[str] = []

    @workflow.signal(name="append")
    def append(self, value: str):
        self.received.append(value)


@registry.workflow()
class SignalWaitOnceWorkflow(_SignalWaitBase):
    """Waits for one ``append`` signal (matches single-signal integration cases)."""

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: len(self.received) >= 1)
        return ",".join(self.received)


@registry.workflow()
class SignalWaitThreeWorkflow(_SignalWaitBase):
    """Waits for three ``append`` signals (matches multi-signal unit-test pattern)."""

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: len(self.received) >= 3)
        return ",".join(self.received)


@registry.workflow()
class StaleWakeupRaceWorkflow:
    def __init__(self) -> None:
        self.cond = False
        self.observed: list[str] = []

    @workflow.run
    async def run(self) -> int:
        async def coro(label: str) -> None:
            await workflow.wait_condition(lambda: self.cond)
            self.observed.append(label)
            self.cond = False  # consume before yielding
            await workflow.sleep(
                timedelta(seconds=1)
            )  # yield after consuming; sibling must not wake

        asyncio.create_task(coro("a"))
        asyncio.create_task(coro("b"))
        await workflow.wait_condition(lambda: len(self.observed) >= 1)
        return len(self.observed)

    @workflow.signal(name="trigger")
    def trigger(self):
        self.cond = True


@registry.workflow()
class AsyncSignalDirectWorkflow:
    """Async signal handler that mutates state without yielding."""

    def __init__(self) -> None:
        self.received: list[str] = []

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: len(self.received) >= 1)
        return self.received[0]

    @workflow.signal(name="append")
    async def append(self, value: str) -> None:
        self.received.append(value)


@registry.workflow()
class AsyncSignalDeferredWorkflow:
    """Async signal handler that yields (workflow.sleep) before mutating state."""

    def __init__(self) -> None:
        self.received: list[str] = []

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: len(self.received) >= 1)
        return self.received[0]

    @workflow.signal(name="append")
    async def append(self, value: str) -> None:
        await workflow.sleep(timedelta(seconds=1))
        self.received.append(value)


@registry.workflow()
class AsyncSignalOrderWorkflow:
    """Two async signal handlers that both yield; delivery order must match history order."""

    def __init__(self) -> None:
        self.log: list[str] = []

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: len(self.log) >= 2)
        return ",".join(self.log)

    @workflow.signal(name="first")
    async def first(self, value: str) -> None:
        await workflow.sleep(timedelta(seconds=1))
        self.log.append(f"first:{value}")

    @workflow.signal(name="second")
    async def second(self, value: str) -> None:
        await workflow.sleep(timedelta(seconds=1))
        self.log.append(f"second:{value}")


def _scan_workflow_outcome(
    response: GetWorkflowExecutionHistoryResponse,
) -> (
    tuple[Literal["completed"], str]
    | tuple[Literal["timed_out"], None]
    | tuple[Literal["failed"], None]
    | tuple[Literal["running"], None]
):
    """Newest-first scan for workflow execution terminal or still-running."""
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


async def _wait_for_workflow_result(
    helper: CadenceHelper,
    execution,
    *,
    deadline_seconds: float = 30.0,
) -> tuple[str, GetWorkflowExecutionHistoryResponse]:
    """Poll full history until the run completes (or times out / fails on the server)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    last: GetWorkflowExecutionHistoryResponse | None = None
    while loop.time() < deadline:
        last = await _get_full_history(helper, execution)
        status, data = _scan_workflow_outcome(last)
        if status == "completed":
            assert data is not None
            return data, last
        if status == "timed_out":
            raise AssertionError(
                "Workflow execution timed out before completion (check worker/signals)"
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


async def _get_full_history(
    helper: CadenceHelper, execution
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


async def test_signal_workflow_unblocks_waiting_workflow(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "SignalWaitOnceWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "append",
            "hello",
        )

        result, _ = await _wait_for_workflow_result(helper, execution)
        assert '"hello"' == result


async def test_signal_with_start_workflow_delivers_initial_signal(
    helper: CadenceHelper,
):
    async with helper.worker(registry) as worker:
        execution = await worker.client.signal_with_start_workflow(
            "SignalWaitOnceWorkflow",
            "append",
            ["same-batch"],
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        result, _ = await _wait_for_workflow_result(helper, execution)
        assert '"same-batch"' == result


async def test_multiple_signals_preserve_history_order(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "SignalWaitThreeWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        for value in ("first", "second", "third"):
            await worker.client.signal_workflow(
                execution.workflow_id,
                execution.run_id,
                "append",
                value,
            )

        result, history = await _wait_for_workflow_result(helper, execution)
        assert '"first,second,third"' == result

        signal_events = [
            event.workflow_execution_signaled_event_attributes.signal_name
            for event in history.history.events
            if event.HasField("workflow_execution_signaled_event_attributes")
        ]
        assert signal_events == ["append", "append", "append"]


async def test_wait_condition_no_stale_wakeup_race(helper: CadenceHelper):
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "StaleWakeupRaceWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "trigger",
        )

        result, _ = await _wait_for_workflow_result(helper, execution)
        # Buggy sweep-all: "2" (sibling waiter fired with stale state).
        # Correct one-per-tick: "1".
        assert "1" == result


async def test_async_signal_handler_direct_mutation(helper: CadenceHelper):
    """Async signal handler that mutates state without yielding completes the workflow."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "AsyncSignalDirectWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
        )

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "append",
            "async-direct",
        )

        result, _ = await _wait_for_workflow_result(helper, execution)
        assert '"async-direct"' == result


async def test_async_signal_handler_deferred_mutation(helper: CadenceHelper):
    """Async handler that yields (workflow.sleep) before mutating still completes."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "AsyncSignalDeferredWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "append",
            "async-deferred",
        )

        result, _ = await _wait_for_workflow_result(helper, execution)
        assert '"async-deferred"' == result


async def test_async_signals_maintain_delivery_order(helper: CadenceHelper):
    """Two async handlers that both yield (workflow.sleep) must run in signal history order."""
    async with helper.worker(registry) as worker:
        execution = await worker.client.start_workflow(
            "AsyncSignalOrderWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )

        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "first",
            "alpha",
        )
        await worker.client.signal_workflow(
            execution.workflow_id,
            execution.run_id,
            "second",
            "beta",
        )

        result, _ = await _wait_for_workflow_result(helper, execution)
        assert '"first:alpha,second:beta"' == result
