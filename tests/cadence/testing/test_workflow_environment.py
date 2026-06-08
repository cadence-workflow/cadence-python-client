from datetime import timedelta

import pytest

from cadence import activity, workflow
from cadence.testing import MockClient, TestWorkflowEnvironment
from cadence.worker import Registry


# --- Sample workflows and activities -------------------------------------


class EchoWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        return f"echo: {value}"


class ActivityWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        result = await workflow.execute_activity(
            "greet",
            str,
            value,
            schedule_to_close_timeout=timedelta(seconds=10),
        )
        return f"workflow:{result}"


class SignalWorkflow:
    def __init__(self) -> None:
        self._approved = False
        self._value = ""

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self._approved)
        return f"approved:{self._value}"

    @workflow.signal(name="approve")
    def approve(self, value: str) -> None:
        self._value = value
        self._approved = True

    @workflow.query(name="status")
    def status(self) -> str:
        return "approved" if self._approved else "pending"


class TimerWorkflow:
    @workflow.run
    async def run(self) -> str:
        await workflow.sleep(timedelta(hours=1))
        return "done"


class ChildWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        return f"child:{value}"


class ParentWorkflow:
    @workflow.run
    async def run(self, value: str) -> str:
        result = await workflow.execute_child_workflow(
            "ChildWorkflow",
            str,
            value,
            execution_start_to_close_timeout=timedelta(seconds=30),
        )
        return f"parent:{result}"


class FailingWorkflow:
    @workflow.run
    async def run(self) -> str:
        raise ValueError("boom")


@activity.defn(name="greet")
async def greet_activity(name: str) -> str:
    return f"hello {name}"


# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def env() -> TestWorkflowEnvironment:
    registry = Registry()
    registry.workflow(EchoWorkflow)
    registry.workflow(ActivityWorkflow)
    registry.workflow(SignalWorkflow)
    registry.workflow(TimerWorkflow)
    registry.workflow(ChildWorkflow)
    registry.workflow(ParentWorkflow)
    registry.workflow(FailingWorkflow)
    environment = TestWorkflowEnvironment(registry)
    yield environment
    environment.close()


# --- Tests ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_is_client_interface(env: TestWorkflowEnvironment):
    assert isinstance(env.client, MockClient)
    from cadence.client import Client

    assert isinstance(env.client, Client)


@pytest.mark.asyncio
async def test_start_simple_workflow(env: TestWorkflowEnvironment):
    execution = await env.client.start_workflow(
        "EchoWorkflow", "world", task_list="tl"
    )
    assert execution.workflow_id
    assert execution.run_id
    assert env.is_workflow_completed(execution.workflow_id)
    assert env.get_workflow_result(str, execution.workflow_id) == "echo: world"


@pytest.mark.asyncio
async def test_real_activity_execution(env: TestWorkflowEnvironment):
    env.register_activity(greet_activity)
    await env.client.start_workflow("ActivityWorkflow", "bob", task_list="tl")
    assert env.get_workflow_result(str) == "workflow:hello bob"


@pytest.mark.asyncio
async def test_mock_activity_with_value(env: TestWorkflowEnvironment):
    env.on_activity("greet", result="mocked!")
    await env.client.start_workflow("ActivityWorkflow", "bob", task_list="tl")
    assert env.get_workflow_result(str) == "workflow:mocked!"


@pytest.mark.asyncio
async def test_mock_activity_with_function(env: TestWorkflowEnvironment):
    env.on_activity("greet", fn=lambda name: f"fn:{name}")
    await env.client.start_workflow("ActivityWorkflow", "carol", task_list="tl")
    assert env.get_workflow_result(str) == "workflow:fn:carol"


@pytest.mark.asyncio
async def test_unmocked_activity_raises(env: TestWorkflowEnvironment):
    await env.client.start_workflow("ActivityWorkflow", "bob", task_list="tl")
    error = env.get_workflow_error()
    assert isinstance(error, KeyError)


@pytest.mark.asyncio
async def test_signal_and_query(env: TestWorkflowEnvironment):
    execution = await env.client.start_workflow("SignalWorkflow", task_list="tl")
    # Workflow is blocked waiting for the signal.
    assert not env.is_workflow_completed(execution.workflow_id)
    assert (
        await env.client.query_workflow(
            execution.workflow_id, "", "status", result_type=str
        )
        == "pending"
    )

    await env.client.signal_workflow(
        execution.workflow_id, "", "approve", "yes"
    )
    assert env.is_workflow_completed(execution.workflow_id)
    assert env.get_workflow_result(str, execution.workflow_id) == "approved:yes"


@pytest.mark.asyncio
async def test_signal_with_start(env: TestWorkflowEnvironment):
    execution = await env.client.signal_with_start_workflow(
        "SignalWorkflow",
        "approve",
        ["instant"],
        task_list="tl",
    )
    assert env.is_workflow_completed(execution.workflow_id)
    assert env.get_workflow_result(str, execution.workflow_id) == "approved:instant"


@pytest.mark.asyncio
async def test_timer_advances_virtual_clock(env: TestWorkflowEnvironment):
    before = env.now()
    await env.client.start_workflow("TimerWorkflow", task_list="tl")
    assert env.get_workflow_result(str) == "done"
    assert env.now() - before == timedelta(hours=1)


@pytest.mark.asyncio
async def test_child_workflow(env: TestWorkflowEnvironment):
    await env.client.start_workflow("ParentWorkflow", "x", task_list="tl")
    assert env.get_workflow_result(str) == "parent:child:x"


@pytest.mark.asyncio
async def test_failing_workflow(env: TestWorkflowEnvironment):
    await env.client.start_workflow("FailingWorkflow", task_list="tl")
    assert env.is_workflow_completed()
    error = env.get_workflow_error()
    assert isinstance(error, ValueError)
    with pytest.raises(ValueError):
        env.get_workflow_result()


@pytest.mark.asyncio
async def test_register_workflow_helper():
    env = TestWorkflowEnvironment()
    try:
        env.register_workflow(EchoWorkflow)
        await env.client.start_workflow("EchoWorkflow", "hi", task_list="tl")
        assert env.get_workflow_result(str) == "echo: hi"
    finally:
        env.close()


@pytest.mark.asyncio
async def test_context_manager_closes():
    with TestWorkflowEnvironment() as env:
        env.register_workflow(EchoWorkflow)
        await env.client.start_workflow("EchoWorkflow", "ctx", task_list="tl")
        assert env.get_workflow_result(str) == "echo: ctx"
