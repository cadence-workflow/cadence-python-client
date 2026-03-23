import asyncio
import inspect
import sys
from cadence import Registry
from tests.cadence.common_activities import (
    ActivityInterface,
    ActivityImpl,
    async_fn,
    echo,
)


def test_sync_activity_fn() -> None:
    reg = Registry()

    reg.register_activity(echo)

    assert inspect.iscoroutinefunction(echo) is False
    # assert asyncio.iscoroutinefunction(echo) is False
    assert reg.get_activity(echo.name) is not None
    # Verify the decorator doesn't interfere with calling the methods
    assert echo("hello") == "hello"


async def test_async_activity_fn() -> None:
    reg = Registry()

    reg.register_activity(async_fn)

    if sys.version_info >= (3, 12):
        # Python 3.11 will fail the async function check and there is nothing we can do about this.
        assert inspect.iscoroutinefunction(async_fn) is True
    assert asyncio.iscoroutinefunction(async_fn) is True
    assert reg.get_activity(async_fn.name) is not None
    # Verify the decorator doesn't interfere with calling the methods
    await async_fn()


def test_activity_interface() -> None:
    impl = ActivityImpl("expected")
    reg = Registry()

    reg.register_activities(impl)

    assert reg.get_activity(ActivityInterface.add.name) is not None
    assert reg.get_activity(ActivityInterface.do_something.name) is not None
    # Verify the decorator doesn't interfere with calling the methods
    assert impl.add(1, 2) == 3
    assert impl.do_something() == "expected"
    assert ActivityImpl.do_something(impl) == "expected"
