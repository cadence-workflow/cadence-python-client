import asyncio
import time
from collections.abc import Iterator
from datetime import timedelta

import pytest

from cadence import activity
from cadence.error import ActivityCancelledError
from cadence.testing import TestActivityEnvironment
from cadence.worker import Registry


# --- Sample activities ----------------------------------------------------


@activity.defn
async def async_echo(name: str) -> str:
    return f"hello {name}"


@activity.defn
def sync_echo(name: str) -> str:
    return f"hello {name}"


@activity.defn
async def add(a: int, b: int) -> int:
    return a + b


@activity.defn
async def boom() -> None:
    raise ValueError("boom")


@activity.defn
async def report_info() -> str:
    info = activity.info()
    return f"{info.activity_type}:{info.task_list}:{info.attempt}"


@activity.defn
async def resume_from_heartbeat() -> list:
    return activity.heartbeat_details(str, int)


@activity.defn
async def resume_from_heartbeat_untyped() -> list:
    return activity.heartbeat_details()


@activity.defn
async def heartbeating() -> str:
    activity.heartbeat("progress", 50)
    return "done"


@activity.defn
async def async_cancellable() -> str:
    try:
        activity.heartbeat("progress")
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        assert activity.is_cancelled()
        raise
    return "should not reach here"


@activity.defn
def sync_cancellable() -> str:
    for _ in range(100):
        if activity.is_cancelled():
            raise ActivityCancelledError("cleanup")
        activity.heartbeat("progress")
        time.sleep(0.01)
    raise AssertionError("expected cancellation")


class GreeterActivities:
    def __init__(self, greeting: str) -> None:
        self._greeting = greeting

    @activity.method(name="greet")
    async def greet(self, name: str) -> str:
        return f"{self._greeting} {name}"


# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def env() -> Iterator[TestActivityEnvironment]:
    environment = TestActivityEnvironment()
    yield environment
    environment.close()


# --- Tests ----------------------------------------------------------------


async def test_execute_async_activity(env: TestActivityEnvironment):
    result = await env.execute_activity(async_echo, "world")
    assert result == "hello world"


async def test_execute_sync_activity(env: TestActivityEnvironment):
    result = await env.execute_activity(sync_echo, "world")
    assert result == "hello world"


async def test_execute_with_positional_args(env: TestActivityEnvironment):
    assert await env.execute_activity(add, 2, 3) == 5


async def test_execute_with_kwargs(env: TestActivityEnvironment):
    assert await env.execute_activity(add, a=2, b=3) == 5


async def test_activity_exception_propagates(env: TestActivityEnvironment):
    with pytest.raises(ValueError, match="boom"):
        await env.execute_activity(boom)


async def test_activity_info_is_populated(env: TestActivityEnvironment):
    result = await env.execute_activity(report_info)
    assert result == "report_info:test-task-list:1"


async def test_execute_by_name(env: TestActivityEnvironment):
    env.register_activity(async_echo)
    result = await env.execute_activity(async_echo.name, "world")
    assert result == "hello world"


async def test_execute_by_unknown_name_raises(env: TestActivityEnvironment):
    with pytest.raises(KeyError):
        await env.execute_activity("does-not-exist")


async def test_register_activities_instance(env: TestActivityEnvironment):
    env.register_activities(GreeterActivities("hi"))
    assert await env.execute_activity("greet", "bob") == "hi bob"


async def test_method_activity_passed_directly(env: TestActivityEnvironment):
    greeter = GreeterActivities("hey")
    assert await env.execute_activity(greeter.greet, "sue") == "hey sue"


async def test_set_heartbeat_details(env: TestActivityEnvironment):
    env.set_heartbeat_details("progress", 42)
    assert await env.execute_activity(resume_from_heartbeat) == ["progress", 42]


async def test_heartbeat_details_empty_by_default(env: TestActivityEnvironment):
    assert await env.execute_activity(resume_from_heartbeat_untyped) == []


async def test_heartbeat_is_recorded(env: TestActivityEnvironment):
    result = await env.execute_activity(heartbeating)
    assert result == "done"
    assert env.heartbeat_count == 1
    assert env.get_heartbeat_details(str, int) == ["progress", 50]


async def test_registry_constructor(env: TestActivityEnvironment):
    registry = Registry()
    registry.register_activity(async_echo)
    environment = TestActivityEnvironment(registry)
    try:
        assert await environment.execute_activity("async_echo", "x") == "hello x"
    finally:
        environment.close()


async def test_async_cancellation(env: TestActivityEnvironment):
    env.cancel()
    with pytest.raises(asyncio.CancelledError):
        await env.execute_activity(async_cancellable)


async def test_sync_cancellation(env: TestActivityEnvironment):
    env.cancel()
    with pytest.raises(ActivityCancelledError):
        await env.execute_activity(sync_cancellable)


async def test_set_test_timeout(env: TestActivityEnvironment):
    @activity.defn
    async def slow() -> str:
        await asyncio.sleep(10)
        return "done"

    env.set_test_timeout(timedelta(milliseconds=50))
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await env.execute_activity(slow)


async def test_context_manager():
    with TestActivityEnvironment() as environment:
        assert await environment.execute_activity(async_echo, "world") == "hello world"
