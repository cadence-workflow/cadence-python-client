from cadence import Registry
from tests.cadence.common_activities import (
    ActivityInterface,
    ActivityImpl,
    echo,
)


def test_activity_fn() -> None:
    reg = Registry()

    reg.register_activity(echo)

    assert reg.get_activity(echo.name) is not None
    # Verify the decorator doesn't interfere with calling the methods
    assert echo("hello") == "hello"


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
