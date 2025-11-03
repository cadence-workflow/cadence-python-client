from cadence.activity import ActivityParameter, ExecutionStrategy
from tests.cadence.common_activities import (
    simple_fn,
    async_echo,
    ActivityInterface,
    Activities,
)


def test_sync():
    definition = simple_fn

    assert definition.name == "simple_fn"
    assert definition.params == []
    assert definition.result_type is None.__class__
    assert definition.strategy == ExecutionStrategy.THREAD_POOL


def test_async():
    definition = async_echo

    assert definition.name == "async_echo"
    assert definition.params == [
        ActivityParameter(
            name="incoming", type_hint=str, has_default=False, default_value=None
        )
    ]
    assert definition.result_type is str
    assert definition.strategy == ExecutionStrategy.ASYNC


def test_interface():
    definition = ActivityInterface.do_something

    assert definition.name == "ActivityInterface.do_something"
    assert definition.params == []
    assert definition.result_type is str
    assert definition.strategy == ExecutionStrategy.THREAD_POOL


def test_class_async():
    definition = Activities.echo_async

    assert definition.name == "Activities.echo_async"
    assert definition.params == [
        ActivityParameter(
            name="incoming", type_hint=str, has_default=False, default_value=None
        )
    ]
    assert definition.result_type is str
    assert definition.strategy == ExecutionStrategy.ASYNC
